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
        self.state_path = STATE_DIR / (nb_path.stem + ".autosave.ipynb")
        self.cells = self._load_cells()
        self.run_lock = asyncio.Lock()
        self.clients = {}  # client_id -> {ws, name, color, cell}
        self.km = None
        self.kc = None
        self._kernel_lock = asyncio.Lock()
        self._save_task = None

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

    # ------------------------------ run ----------------------------------- #
    async def run_cell(self, cell_id):
        cell = self.by_id(cell_id)
        if not cell or cell["cell_type"] != "code":
            return
        await self.ensure_kernel()
        async with self.run_lock:
            cell["outputs"] = []
            cell["running"] = True
            cell["execution_count"] = None
            await self.broadcast({"type": "run_start", "cellId": cell_id})
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
                    cell["outputs"].append(out)
                    await self.broadcast({"type": "output", "cellId": cell_id, "output": out})
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
                            o = {"output_type": "stream", "name": "stdout",
                                 "text": ANSI.sub("", text)}
                            cell["outputs"].append(o)
                            await self.broadcast({"type": "output", "cellId": cell_id, "output": o})
                break
            cell["running"] = False
            await self.broadcast({"type": "run_done", "cellId": cell_id,
                                  "execution_count": cell["execution_count"]})
            self.schedule_autosave()

    async def run_all(self):
        for c in list(self.cells):
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
        mtime = (self.state_path if has_autosave else self.nb_path).stat().st_mtime
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


def init_sessions():
    for p in discover_notebooks():
        slug = slug_for(p)
        sessions[slug] = Session(slug, p)


init_sessions()


# --------------------------------------------------------------------------- #
# Linting (pyflakes). Lint the target cell for its own syntax errors, and use
# the concatenation of ALL code cells for name/usage warnings, so names defined
# in other cells don't produce false "undefined name" / "unused import" noise.
# --------------------------------------------------------------------------- #
def lint_cell(sources, idx):
    if idx < 0 or idx >= len(sources):
        return []
    target = sources[idx]
    try:
        ast.parse(target)
    except SyntaxError as e:
        return [{"line": (e.lineno or 1) - 1,
                 "col": max((e.offset or 1) - 1, 0),
                 "message": f"SyntaxError: {e.msg}", "severity": "error"}]
    if _PyflakesChecker is None:
        return []
    combined, offsets, ln = "", [], 1
    for s in sources:
        offsets.append(ln)
        combined += s + "\n"
        ln += s.count("\n") + 1
    start = offsets[idx]
    end = start + target.count("\n")
    out = []
    try:
        tree = ast.parse(combined)
        checker = _PyflakesChecker(tree, filename="cells")
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
    infos = [s.info() for s in sessions.values()]
    infos.sort(key=lambda x: x["last_modified"], reverse=True)
    return infos


@app.post("/lint/{slug}")
async def lint(slug: str, request: Request):
    data = await request.json()
    return lint_cell(data.get("sources", []), int(data.get("index", 0)))


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
        return FileResponse(ROOT / "static" / "sessions.html")
    return FileResponse(ROOT / "static" / "notebook.html")


@app.websocket("/ws/{slug}")
async def ws(websocket: WebSocket, slug: str):
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
                asyncio.create_task(session.run_cell(msg["cellId"]))
            elif t == "run_all":
                asyncio.create_task(session.run_all())
            elif t == "interrupt":
                if session.km is not None:
                    await session.km.interrupt_kernel()
            elif t == "presence":
                session.clients[cid]["cell"] = msg.get("cell")
                await session.broadcast({"type": "presence", "users": session.presence()})
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
