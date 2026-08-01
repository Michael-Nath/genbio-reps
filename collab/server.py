"""
Live collaborative notebook server.

Two+ people connect over WebSocket and share ONE view of a notebook: same cells,
same edits, same outputs, in real time. Code runs against a single live Jupyter
kernel so outputs (text, matplotlib images, tracebacks) are genuine.

The server auto-discovers every `.ipynb` under the repo and exposes each as its
own session (own cells, own kernel, own autosave sidecar) — "/" lists them all,
"/n/<slug>" opens one. Kernels start lazily on first connection.

Run:  ./run.sh   (or)   .venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000
"""
import ast
import asyncio
import json
import re
import uuid
from pathlib import Path

import nbformat
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from jupyter_client.manager import AsyncKernelManager

try:
    from pyflakes.checker import Checker as _PyflakesChecker
except Exception:
    _PyflakesChecker = None

try:
    # Jupyter's own input transformer. Lets the linter see what the *kernel*
    # sees, so `np.array?`, `%timeit`, and `!pip install` aren't syntax errors.
    from IPython.core.inputtransformer2 import TransformerManager
    _ipy_transform = TransformerManager().transform_cell
except Exception:
    _ipy_transform = None

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent

ANSI = re.compile(r"\x1b\[[0-9;]*m")
COLORS = ["#e6194B", "#3cb44b", "#4363d8", "#f58231",
          "#911eb4", "#00b8a9", "#f032e6", "#bfa100"]

# Autosave sidecars: full live state (incl. outputs) so a server restart resumes
# where you left off. Gitignored; the pristine notebook is only touched by "Save".
STATE_DIR = ROOT / ".state"

EXCLUDE_DIRS = {".venv", "venv", "node_modules", ".git",
                ".ipynb_checkpoints", "collab", "__pycache__"}

# Cap on retained stdout/stderr per cell. A runaway training loop shouldn't be
# able to grow the autosave file (or a joiner's payload) without bound.
MAX_STREAM_CHARS = 200_000


def discover_notebooks():
    found = []
    for p in sorted(REPO_ROOT.rglob("*.ipynb")):
        rel_parts = p.relative_to(REPO_ROOT).parts
        if any(part in EXCLUDE_DIRS for part in rel_parts):
            continue
        found.append(p)
    return found


def slug_for(path: Path) -> str:
    rel = str(path.relative_to(REPO_ROOT).with_suffix("")).replace("/", "--")
    return re.sub(r"[^a-zA-Z0-9_-]", "-", rel)


# --------------------------------------------------------------------------- #
# Per-notebook session: cells, kernel, clients — everything scoped to one .ipynb
# --------------------------------------------------------------------------- #
def _outputs_from_nb(cell):
    outs = []
    for o in cell.get("outputs", []):
        ot = o.get("output_type")
        if ot == "stream":
            outs.append({"output_type": "stream",
                         "name": o.get("name", "stdout"), "text": o.get("text", "")})
        elif ot in ("execute_result", "display_data"):
            outs.append({"output_type": ot, "data": dict(o.get("data", {}))})
        elif ot == "error":
            outs.append({"output_type": "error", "ename": o.get("ename", ""),
                         "evalue": o.get("evalue", ""),
                         "traceback": list(o.get("traceback", []))})
    return outs


class Session:
    def __init__(self, slug, nb_path):
        self.slug = slug
        self.nb_path = nb_path
        # Keyed on the slug, not the stem: two notebooks with the same filename
        # in different folders must not share one sidecar.
        self.state_path = STATE_DIR / (slug + ".autosave.ipynb")
        self._migrate_legacy_state()
        self.cells = self._load_cells()
        self.run_lock = asyncio.Lock()
        self.clients = {}  # client_id -> {ws, name, color, cell}
        self.km = None
        self.kc = None
        self._kernel_lock = asyncio.Lock()
        self._save_task = None
        self._stop_all = False
        self._pending_runs = set()
        self._run_all_task = None

    def _migrate_legacy_state(self):
        """Adopt a sidecar written before sidecars were slug-keyed.

        Old name was `<stem>.autosave.ipynb`. Claim it once, so existing work
        carries over instead of silently reverting to the pristine notebook.
        """
        legacy = STATE_DIR / (self.nb_path.stem + ".autosave.ipynb")
        if legacy == self.state_path or not legacy.exists():
            return
        if self.state_path.exists():
            return
        try:
            legacy.rename(self.state_path)
            print(f"[{self.slug}] migrated autosave {legacy.name} -> {self.state_path.name}")
        except OSError as e:
            print(f"[{self.slug}] could not migrate {legacy.name}:", e)

    def _load_cells(self):
        # prefer the autosaved working state; fall back to the original notebook
        path = self.state_path if self.state_path.exists() else self.nb_path
        nb = nbformat.read(path, as_version=4)
        cells = []
        for c in nb.cells:
            is_code = c.cell_type == "code"
            cells.append({
                "id": (c.get("id") or uuid.uuid4().hex[:8]),
                "cell_type": c.cell_type,
                "source": c.source,
                "outputs": _outputs_from_nb(c) if is_code else [],
                "execution_count": c.get("execution_count") if is_code else None,
                "running": False,
            })
        return cells

    def by_id(self, cid):
        for c in self.cells:
            if c["id"] == cid:
                return c
        return None

    def presence(self):
        return [
            {"id": cid, "name": i["name"], "color": i["color"], "cell": i.get("cell")}
            for cid, i in self.clients.items()
        ]

    async def broadcast(self, msg, exclude=None):
        data = json.dumps(msg)
        dead = []
        for cid, info in list(self.clients.items()):
            if cid == exclude:
                continue
            try:
                await info["ws"].send_text(data)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.clients.pop(cid, None)

    # ----------------------------- kernel -------------------------------- #
    async def ensure_kernel(self):
        if self.kc is not None:
            return
        async with self._kernel_lock:
            if self.kc is not None:
                return
            self.km = AsyncKernelManager(kernel_name="python3")
            await self.km.start_kernel(cwd=str(self.nb_path.parent))
            self.kc = self.km.client()
            self.kc.start_channels()
            try:
                await self.kc.wait_for_ready(timeout=60)
            except RuntimeError as e:
                print(f"[{self.slug}] kernel not ready:", e)
            # make matplotlib figures render inline as PNGs in the shared view
            await self._silent_exec("%matplotlib inline")

    async def _silent_exec(self, code):
        """Run code with no broadcast; drain its iopub messages until idle."""
        msg_id = self.kc.execute(code, store_history=False)
        while True:
            try:
                msg = await self.kc.get_iopub_msg(timeout=30)
            except Exception:
                return
            if msg["parent_header"].get("msg_id") != msg_id:
                continue
            if msg["msg_type"] == "status" and msg["content"]["execution_state"] == "idle":
                try:
                    await self.kc.get_shell_msg(timeout=5)   # drain the shell reply
                except Exception:
                    pass
                return

    async def shutdown_kernel(self):
        if self.km is not None:
            try:
                await self.km.shutdown_kernel(now=True)
            except Exception:
                pass

    async def restart_kernel(self):
        """Wipe the shared namespace and start clean — the escape hatch for a
        wedged kernel, which otherwise needed killing the whole server."""
        self._stop_all = True
        if self.km is None:
            await self.ensure_kernel()
        else:
            async with self._kernel_lock:
                try:
                    await self.km.restart_kernel(now=True)
                    await self.kc.wait_for_ready(timeout=60)
                except Exception as e:
                    print(f"[{self.slug}] restart failed:", e)
                await self._silent_exec("%matplotlib inline")
        for c in self.cells:
            c["execution_count"] = None
            c["running"] = False
        await self.broadcast({"type": "kernel_restarted"})
        self.schedule_autosave()

    async def interrupt(self):
        """Stop the current cell and abandon the rest of a Run all."""
        self._stop_all = True
        if self.km is not None:
            await self.km.interrupt_kernel()

    # ------------------------------ run ----------------------------------- #
    async def _emit(self, cell, out):
        """Record an output and push it to everyone.

        Consecutive chunks on the same stream are merged, the way Jupyter does
        it: a loop printing 10k lines becomes one output instead of 10k, which
        keeps the autosave, the .ipynb, and a late joiner's `init` payload sane.
        Only the tail is kept past MAX_STREAM_CHARS — for a training loop the
        last lines are the ones you want.
        """
        outs = cell["outputs"]
        if (out["output_type"] == "stream" and outs
                and outs[-1]["output_type"] == "stream"
                and outs[-1]["name"] == out["name"]):
            merged = outs[-1]["text"] + out["text"]
            outs[-1]["text"] = merged[-MAX_STREAM_CHARS:]
        else:
            outs.append(out)
        await self.broadcast({"type": "output", "cellId": cell["id"], "output": out})

    def queue_run(self, cell_id, by=None):
        """Schedule one execution of a cell, at most once at a time.

        Two people hammering Shift-Enter on the same cell used to spawn a task
        per keypress, all of them queueing on run_lock and re-running the cell.
        Collapsing to one pending execution keeps the shared kernel sane.
        """
        if cell_id in self._pending_runs:
            return
        cell = self.by_id(cell_id)
        if not cell or cell["cell_type"] != "code":
            return
        self._pending_runs.add(cell_id)

        async def _go():
            try:
                await self.run_cell(cell_id, by=by)
            finally:
                self._pending_runs.discard(cell_id)

        asyncio.create_task(_go())

    def queue_run_all(self):
        if self._run_all_task and not self._run_all_task.done():
            return                     # already sweeping; don't interleave
        self._run_all_task = asyncio.create_task(self.run_all())

    async def run_cell(self, cell_id, by=None):
        cell = self.by_id(cell_id)
        if not cell or cell["cell_type"] != "code":
            return
        await self.ensure_kernel()
        async with self.run_lock:
            cell["outputs"] = []
            cell["running"] = True
            cell["execution_count"] = None
            # `by` lets every other client follow the runner to this cell.
            await self.broadcast({"type": "run_start", "cellId": cell_id, "by": by})
            try:
                msg_id = self.kc.execute(cell["source"])
                while True:
                    try:
                        msg = await self.kc.get_iopub_msg(timeout=120)
                    except Exception:
                        break
                    if msg["parent_header"].get("msg_id") != msg_id:
                        continue
                    mtype = msg["msg_type"]
                    content = msg["content"]
                    out = None
                    if mtype == "status":
                        if content["execution_state"] == "idle":
                            break
                    elif mtype == "execute_input":
                        cell["execution_count"] = content.get("execution_count")
                    elif mtype == "stream":
                        out = {"output_type": "stream",
                               "name": content["name"], "text": content["text"]}
                    elif mtype in ("execute_result", "display_data"):
                        out = {"output_type": mtype, "data": content["data"]}
                    elif mtype == "error":
                        out = {"output_type": "error",
                               "ename": content["ename"],
                               "evalue": content["evalue"],
                               "traceback": [ANSI.sub("", t) for t in content["traceback"]]}
                    if out is not None:
                        await self._emit(cell, out)
                # Drain the shell reply and surface `obj?` / `obj??` help, which IPython
                # returns as a "page" payload on the shell channel (not via iopub).
                for _ in range(10):
                    try:
                        reply = await self.kc.get_shell_msg(timeout=5)
                    except Exception:
                        break
                    if reply["parent_header"].get("msg_id") != msg_id:
                        continue
                    for p in reply["content"].get("payload", []):
                        if p.get("source") == "page":
                            text = p.get("data", {}).get("text/plain", "")
                            if text:
                                await self._emit(cell, {"output_type": "stream",
                                                        "name": "stdout",
                                                        "text": ANSI.sub("", text)})
                    break
            finally:
                # Never leave a cell stuck on [*] — a dead kernel or a dropped
                # channel must still clear the spinner for everyone.
                cell["running"] = False
                await self.broadcast({"type": "run_done", "cellId": cell_id,
                                      "execution_count": cell["execution_count"]})
                self.schedule_autosave()

    async def run_all(self):
        self._stop_all = False
        for c in list(self.cells):
            if self._stop_all:      # Interrupt abandons the queue, as in Jupyter
                break
            if c["cell_type"] == "code":
                await self.run_cell(c["id"])

    # ---------------------------- persistence ------------------------------ #
    def write_nb(self, path):
        nb = nbformat.v4.new_notebook()
        nb.metadata = {"kernelspec": {"display_name": "Python 3",
                                      "language": "python", "name": "python3"},
                       "language_info": {"name": "python"}}
        out_cells = []
        for c in self.cells:
            if c["cell_type"] == "markdown":
                out_cells.append(nbformat.v4.new_markdown_cell(c["source"], id=c["id"]))
            else:
                cell = nbformat.v4.new_code_cell(c["source"], id=c["id"])
                cell.execution_count = c["execution_count"]
                outs = []
                for o in c["outputs"]:
                    if o["output_type"] == "stream":
                        outs.append(nbformat.v4.new_output("stream", name=o["name"],
                                                           text=o["text"]))
                    elif o["output_type"] in ("execute_result", "display_data"):
                        outs.append(nbformat.v4.new_output(
                            o["output_type"], data=o["data"],
                            execution_count=c["execution_count"]))
                    elif o["output_type"] == "error":
                        outs.append(nbformat.v4.new_output(
                            "error", ename=o["ename"], evalue=o["evalue"],
                            traceback=o["traceback"]))
                cell.outputs = outs
                out_cells.append(cell)
        nb.cells = out_cells
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        nbformat.write(nb, str(path))

    def save_notebook(self):
        """Explicit save -> the real, tracked notebook (the 💾 button)."""
        self.write_nb(self.nb_path)
        self.autosave_now()

    def autosave_now(self):
        """Persist live working state -> gitignored sidecar (survives restarts)."""
        try:
            self.write_nb(self.state_path)
        except Exception as e:
            print(f"[{self.slug}] autosave failed:", e)

    def schedule_autosave(self, delay=1.2):
        """Debounced autosave; coalesces bursts of edits into one write."""
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()

        async def _later():
            try:
                await asyncio.sleep(delay)
                self.autosave_now()
            except asyncio.CancelledError:
                pass

        self._save_task = asyncio.create_task(_later())

    # ------------------------------- info ----------------------------------- #
    def info(self):
        has_autosave = self.state_path.exists()
        try:
            mtime = (self.state_path if has_autosave else self.nb_path).stat().st_mtime
        except OSError:      # notebook deleted out from under a live session
            mtime = 0.0
        return {
            "slug": self.slug,
            "name": self.nb_path.stem,
            "path": str(self.nb_path.relative_to(REPO_ROOT)),
            "has_autosave": has_autosave,
            "kernel_running": self.kc is not None,
            "client_count": len(self.clients),
            "cell_count": len(self.cells),
            "last_modified": mtime,
            "users": [{"name": i["name"], "color": i["color"]} for i in self.clients.values()],
        }


sessions: dict[str, Session] = {}


def sync_sessions():
    """Rescan the repo for notebooks.

    Called on startup and whenever the session list is fetched, so a notebook
    added (or renamed, or deleted) while the server is up shows up without a
    restart. A session with people or a kernel in it is never dropped.
    """
    seen = set()
    for p in discover_notebooks():
        slug = slug_for(p)
        seen.add(slug)
        if slug not in sessions:
            sessions[slug] = Session(slug, p)
    for slug in [s for s in sessions if s not in seen]:
        s = sessions[slug]
        if not s.clients and s.kc is None:
            sessions.pop(slug, None)


sync_sessions()


# --------------------------------------------------------------------------- #
# Linting (pyflakes). Lint the target cell for its own syntax errors, and use
# the concatenation of ALL code cells for name/usage warnings, so names defined
# in other cells don't produce false "undefined name" / "unused import" noise.
# --------------------------------------------------------------------------- #

# Names IPython injects into the namespace. Real at runtime, invisible to
# pyflakes — without these, every transformed magic reports "undefined name".
_IPY_BUILTINS = ["get_ipython", "display", "In", "Out", "exit", "quit"]


def _to_python(src):
    """IPython source -> plain Python, plus whether line numbers survived.

    Line magics (`%timeit x`), shell escapes (`!pip ...`) and `obj?` each map to
    one line, so diagnostics stay aligned. A cell magic (`%%time`) collapses the
    whole cell to a single call: we keep the transformed text so names defined
    there still resolve for other cells, but flag it as unaligned so we don't
    report diagnostics against the wrong lines.
    """
    if _ipy_transform is None:
        return src, True
    try:
        out = _ipy_transform(src)
    except Exception:
        return src, True   # transformer choked (mid-typing); lint the raw text
    return out, len(out.splitlines()) == len(src.splitlines())


def lint_cell(sources, idx):
    if idx < 0 or idx >= len(sources):
        return []
    transformed = [_to_python(s) for s in sources]
    target, aligned = transformed[idx]
    try:
        ast.parse(target)
    except SyntaxError as e:
        if not aligned:
            return []
        return [{"line": (e.lineno or 1) - 1,
                 "col": max((e.offset or 1) - 1, 0),
                 "message": f"SyntaxError: {e.msg}", "severity": "error"}]
    if _PyflakesChecker is None or not aligned:
        return []
    combined, offsets, ln = "", [], 1
    for s, _ in transformed:
        offsets.append(ln)
        combined += s + "\n"
        ln += s.count("\n") + 1
    start = offsets[idx]
    end = start + max(len(target.splitlines()), 1) - 1
    out = []
    try:
        tree = ast.parse(combined)
        checker = _PyflakesChecker(tree, filename="cells", builtins=_IPY_BUILTINS)
        for m in checker.messages:
            if start <= m.lineno <= end:
                out.append({"line": m.lineno - start,
                            "col": getattr(m, "col", 0),
                            "message": m.message % m.message_args,
                            "severity": "warning"})
    except SyntaxError:
        pass
    return out


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
app = FastAPI()


@app.get("/api/sessions")
async def api_sessions():
    sync_sessions()
    infos = [s.info() for s in sessions.values()]
    infos.sort(key=lambda x: x["last_modified"], reverse=True)
    return infos


@app.post("/lint/{slug}")
async def lint(slug: str, request: Request):
    data = await request.json()
    if "sources" in data:                    # explicit form, used by test_client
        return lint_cell(data["sources"], int(data.get("index", 0)))
    # Normal path: the client sends only the cell it's typing in. The server
    # already holds every other cell's source, so a keystroke no longer ships
    # the whole notebook — that was the main source of lag when two people
    # typed at once over a tunnel.
    session = sessions.get(slug)
    if session is None:
        return []
    sources, idx = [], -1
    for c in session.cells:
        if c["cell_type"] != "code":
            continue
        if c["id"] == data.get("cellId"):
            idx = len(sources)
            sources.append(data.get("source", ""))
        else:
            sources.append(c["source"])
    return lint_cell(sources, idx) if idx >= 0 else []


@app.on_event("shutdown")
async def _shutdown():
    for s in sessions.values():
        await s.shutdown_kernel()


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "sessions.html")


@app.get("/n/{slug}")
async def notebook_page(slug: str):
    if slug not in sessions:
        sync_sessions()          # may be a notebook added since startup
    if slug not in sessions:
        return FileResponse(ROOT / "static" / "sessions.html")
    return FileResponse(ROOT / "static" / "notebook.html")


@app.websocket("/ws/{slug}")
async def ws(websocket: WebSocket, slug: str):
    if slug not in sessions:
        sync_sessions()
    session = sessions.get(slug)
    if session is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    await session.ensure_kernel()
    cid = uuid.uuid4().hex[:8]
    color = COLORS[len(session.clients) % len(COLORS)]
    session.clients[cid] = {"ws": websocket, "name": "guest", "color": color, "cell": None}
    await websocket.send_text(json.dumps({
        "type": "init", "clientId": cid, "color": color,
        "notebook": session.nb_path.name, "cells": session.cells, "users": session.presence(),
    }))
    await session.broadcast({"type": "presence", "users": session.presence()})
    try:
        while True:
            msg = json.loads(await websocket.receive_text())
            t = msg.get("type")
            if t == "hello":
                session.clients[cid]["name"] = str(msg.get("name", "guest"))[:24]
                await session.broadcast({"type": "presence", "users": session.presence()})
            elif t == "edit":
                c = session.by_id(msg["cellId"])
                if c is not None:
                    c["source"] = msg["source"]
                await session.broadcast({"type": "edit", "cellId": msg["cellId"],
                                         "source": msg["source"], "from": cid}, exclude=cid)
                session.schedule_autosave()
            elif t == "run":
                session.queue_run(msg["cellId"], by=cid)
            elif t == "run_all":
                session.queue_run_all()
            elif t == "interrupt":
                await session.interrupt()
            elif t == "restart":
                asyncio.create_task(session.restart_kernel())
            elif t == "presence":
                session.clients[cid]["cell"] = msg.get("cell")
                await session.broadcast({"type": "presence", "users": session.presence()})
            elif t == "cursor":
                # ephemeral: relay a client's in-editor caret/selection to everyone else
                await session.broadcast({"type": "cursor", "cellId": msg.get("cellId"),
                                         "from": cid, "anchor": msg.get("anchor"),
                                         "head": msg.get("head")}, exclude=cid)
            elif t == "add":
                new = {"id": uuid.uuid4().hex[:8],
                       "cell_type": msg.get("cellType", "code"),
                       "source": msg.get("source", ""), "outputs": [],
                       "execution_count": None, "running": False}
                # insert after afterId; unknown/empty afterId -> insert at top
                idx = next((i for i, c in enumerate(session.cells)
                            if c["id"] == msg.get("afterId")), -1)
                session.cells.insert(idx + 1, new)
                await session.broadcast({"type": "add", "cell": new,
                                         "afterId": msg.get("afterId")})
                session.schedule_autosave()
            elif t == "settype":
                c = session.by_id(msg["cellId"])
                if c is not None:
                    c["cell_type"] = msg["cellType"]
                    c["outputs"] = []
                    c["execution_count"] = None
                await session.broadcast({"type": "settype", "cellId": msg["cellId"],
                                         "cellType": msg["cellType"]})
                session.schedule_autosave()
            elif t == "delete":
                session.cells = [c for c in session.cells if c["id"] != msg["cellId"]]
                await session.broadcast({"type": "delete", "cellId": msg["cellId"]})
                session.schedule_autosave()
            elif t == "save":
                session.save_notebook()
                await session.broadcast({"type": "saved"})
    except WebSocketDisconnect:
        pass
    finally:
        session.clients.pop(cid, None)
        await session.broadcast({"type": "presence", "users": session.presence()})


app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
