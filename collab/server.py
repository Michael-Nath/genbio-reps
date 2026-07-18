"""
Live collaborative notebook server.

Two+ people connect over WebSocket and share ONE view of a notebook: same cells,
same edits, same outputs, in real time. Code runs against a single live Jupyter
kernel so outputs (text, matplotlib images, tracebacks) are genuine.

Run:  ./run.sh   (or)   NB_PATH=../00_foundations/01_proteins_as_tensors.ipynb \
                        .venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000
"""
import ast
import asyncio
import json
import os
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
NB_PATH = Path(
    os.environ.get(
        "NB_PATH", ROOT.parent / "00_foundations" / "01_proteins_as_tensors.ipynb"
    )
).resolve()

ANSI = re.compile(r"\x1b\[[0-9;]*m")
COLORS = ["#e6194B", "#3cb44b", "#4363d8", "#f58231",
          "#911eb4", "#00b8a9", "#f032e6", "#bfa100"]

# Autosave sidecar: full live state (incl. outputs) so a server restart resumes
# where you left off. Gitignored; the pristine notebook is only touched by "Save".
STATE_DIR = ROOT / ".state"
STATE_PATH = STATE_DIR / (NB_PATH.stem + ".autosave.ipynb")


# --------------------------------------------------------------------------- #
# Shared notebook state
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


def load_cells():
    # prefer the autosaved working state; fall back to the original notebook
    path = STATE_PATH if STATE_PATH.exists() else NB_PATH
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


class State:
    def __init__(self):
        self.cells = load_cells()
        self.run_lock = asyncio.Lock()

    def by_id(self, cid):
        for c in self.cells:
            if c["id"] == cid:
                return c
        return None


state = State()
clients = {}  # client_id -> {ws, name, color, cell}


def presence():
    return [
        {"id": cid, "name": i["name"], "color": i["color"], "cell": i.get("cell")}
        for cid, i in clients.items()
    ]


async def broadcast(msg, exclude=None):
    data = json.dumps(msg)
    dead = []
    for cid, info in list(clients.items()):
        if cid == exclude:
            continue
        try:
            await info["ws"].send_text(data)
        except Exception:
            dead.append(cid)
    for cid in dead:
        clients.pop(cid, None)


# --------------------------------------------------------------------------- #
# Kernel
# --------------------------------------------------------------------------- #
km = AsyncKernelManager(kernel_name="python3")
kc = None


async def _silent_exec(code):
    """Run code with no broadcast; drain its iopub messages until idle."""
    msg_id = kc.execute(code, store_history=False)
    while True:
        try:
            msg = await kc.get_iopub_msg(timeout=30)
        except Exception:
            return
        if msg["parent_header"].get("msg_id") != msg_id:
            continue
        if msg["msg_type"] == "status" and msg["content"]["execution_state"] == "idle":
            try:
                await kc.get_shell_msg(timeout=5)   # drain the shell reply
            except Exception:
                pass
            return


async def start_kernel():
    global kc
    await km.start_kernel(cwd=str(NB_PATH.parent))
    kc = km.client()
    kc.start_channels()
    try:
        await kc.wait_for_ready(timeout=60)
    except RuntimeError as e:
        print("kernel not ready:", e)
    # make matplotlib figures render inline as PNGs in the shared view
    await _silent_exec("%matplotlib inline")


async def run_cell(cell_id):
    cell = state.by_id(cell_id)
    if not cell or cell["cell_type"] != "code" or kc is None:
        return
    async with state.run_lock:
        cell["outputs"] = []
        cell["running"] = True
        cell["execution_count"] = None
        await broadcast({"type": "run_start", "cellId": cell_id})
        msg_id = kc.execute(cell["source"])
        while True:
            try:
                msg = await kc.get_iopub_msg(timeout=120)
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
                await broadcast({"type": "output", "cellId": cell_id, "output": out})
        # Drain the shell reply and surface `obj?` / `obj??` help, which IPython
        # returns as a "page" payload on the shell channel (not via iopub).
        for _ in range(10):
            try:
                reply = await kc.get_shell_msg(timeout=5)
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
                        await broadcast({"type": "output", "cellId": cell_id, "output": o})
            break
        cell["running"] = False
        await broadcast({"type": "run_done", "cellId": cell_id,
                         "execution_count": cell["execution_count"]})
        schedule_autosave()


async def run_all():
    for c in list(state.cells):
        if c["cell_type"] == "code":
            await run_cell(c["id"])


def write_nb(path):
    nb = nbformat.v4.new_notebook()
    nb.metadata = {"kernelspec": {"display_name": "Python 3",
                                  "language": "python", "name": "python3"},
                   "language_info": {"name": "python"}}
    out_cells = []
    for c in state.cells:
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


def save_notebook():
    """Explicit save -> the real, tracked notebook (the 💾 button)."""
    write_nb(NB_PATH)
    autosave_now()


def autosave_now():
    """Persist live working state -> gitignored sidecar (survives restarts)."""
    try:
        write_nb(STATE_PATH)
    except Exception as e:
        print("autosave failed:", e)


_save_task = None


def schedule_autosave(delay=1.2):
    """Debounced autosave; coalesces bursts of edits into one write."""
    global _save_task
    if _save_task and not _save_task.done():
        _save_task.cancel()

    async def _later():
        try:
            await asyncio.sleep(delay)
            autosave_now()
        except asyncio.CancelledError:
            pass

    _save_task = asyncio.create_task(_later())


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


@app.post("/lint")
async def lint(request: Request):
    data = await request.json()
    return lint_cell(data.get("sources", []), int(data.get("index", 0)))


@app.on_event("startup")
async def _startup():
    await start_kernel()


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    cid = uuid.uuid4().hex[:8]
    color = COLORS[len(clients) % len(COLORS)]
    clients[cid] = {"ws": websocket, "name": "guest", "color": color, "cell": None}
    await websocket.send_text(json.dumps({
        "type": "init", "clientId": cid, "color": color,
        "notebook": NB_PATH.name, "cells": state.cells, "users": presence(),
    }))
    await broadcast({"type": "presence", "users": presence()})
    try:
        while True:
            msg = json.loads(await websocket.receive_text())
            t = msg.get("type")
            if t == "hello":
                clients[cid]["name"] = str(msg.get("name", "guest"))[:24]
                await broadcast({"type": "presence", "users": presence()})
            elif t == "edit":
                c = state.by_id(msg["cellId"])
                if c is not None:
                    c["source"] = msg["source"]
                await broadcast({"type": "edit", "cellId": msg["cellId"],
                                 "source": msg["source"], "from": cid}, exclude=cid)
                schedule_autosave()
            elif t == "run":
                asyncio.create_task(run_cell(msg["cellId"]))
            elif t == "run_all":
                asyncio.create_task(run_all())
            elif t == "interrupt":
                await km.interrupt_kernel()
            elif t == "presence":
                clients[cid]["cell"] = msg.get("cell")
                await broadcast({"type": "presence", "users": presence()})
            elif t == "add":
                new = {"id": uuid.uuid4().hex[:8],
                       "cell_type": msg.get("cellType", "code"),
                       "source": msg.get("source", ""), "outputs": [],
                       "execution_count": None, "running": False}
                # insert after afterId; unknown/empty afterId -> insert at top
                idx = next((i for i, c in enumerate(state.cells)
                            if c["id"] == msg.get("afterId")), -1)
                state.cells.insert(idx + 1, new)
                await broadcast({"type": "add", "cell": new,
                                 "afterId": msg.get("afterId")})
                schedule_autosave()
            elif t == "settype":
                c = state.by_id(msg["cellId"])
                if c is not None:
                    c["cell_type"] = msg["cellType"]
                    c["outputs"] = []
                    c["execution_count"] = None
                await broadcast({"type": "settype", "cellId": msg["cellId"],
                                 "cellType": msg["cellType"]})
                schedule_autosave()
            elif t == "delete":
                state.cells = [c for c in state.cells if c["id"] != msg["cellId"]]
                await broadcast({"type": "delete", "cellId": msg["cellId"]})
                schedule_autosave()
            elif t == "save":
                save_notebook()
                await broadcast({"type": "saved"})
    except WebSocketDisconnect:
        pass
    finally:
        clients.pop(cid, None)
        await broadcast({"type": "presence", "users": presence()})


app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
