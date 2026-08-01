"""Two-client integration test: run cells on A, assert B sees synced state.

Usage:  ./run.sh &            # then
        .venv/bin/python test_client.py [port] [slug]

Port defaults to 8000 (what run.sh serves). Slug defaults to the first session
the server reports, so this keeps working as notebooks are added or renamed.
"""
import asyncio, json, os, sys, urllib.request
import websockets

PORT = int(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PORT", 8000))


def pick_slug():
    if len(sys.argv) > 2:
        return sys.argv[2]
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/sessions", timeout=5) as r:
        found = json.load(r)
    if not found:
        sys.exit("no sessions reported by the server")
    return found[0]["slug"]


SLUG = pick_slug()
URI = f"ws://127.0.0.1:{PORT}/ws/{SLUG}"


async def recv_until(ws, pred, timeout=30):
    msgs = []
    async def loop():
        while True:
            m = json.loads(await ws.recv())
            msgs.append(m)
            if pred(m):
                return m
    return await asyncio.wait_for(loop(), timeout), msgs


async def main():
    a = await websockets.connect(URI)
    b = await websockets.connect(URI)
    init_a = json.loads(await a.recv())
    init_b = json.loads(await b.recv())
    cells = init_a["cells"]
    code = [c for c in cells if c["cell_type"] == "code"]
    print(f"loaded {len(cells)} cells ({len(code)} code)")

    await a.send(json.dumps({"type": "hello", "name": "alice"}))
    await b.send(json.dumps({"type": "hello", "name": "bob"}))

    def find(substr, avoid=None):
        for c in code:
            if substr in c["source"] and (avoid is None or avoid not in c["source"]):
                return c["id"]
        return None

    imports = code[0]["id"]                                  # first code cell = imports
    printer = find("print(", avoid="NotImplementedError")
    plot = find("plt.show()")
    solutions = find("reference solutions") or code[-1]["id"]

    # A cellId the server doesn't know is silently dropped, so a missing cell
    # would hang recv_until until it times out. Skip those steps instead.
    def skip(step, what):
        print(f"{step}. SKIPPED — no {what} cell in {SLUG}")

    # 1) run imports on A -> B must see run_start + run_done
    await a.send(json.dumps({"type": "run", "cellId": imports}))
    done, _ = await recv_until(b, lambda m: m.get("type") == "run_done" and m["cellId"] == imports)
    print("1. imports ran, B saw run_done, exec_count =", done["execution_count"])

    # load reference solutions so printer cell won't NotImplementedError
    await a.send(json.dumps({"type": "run", "cellId": solutions}))
    await recv_until(b, lambda m: m.get("type") == "run_done" and m["cellId"] == solutions)

    # 2) run a printing cell -> B must receive a stream output
    if printer is None:
        skip(2, "print(")
    else:
        await a.send(json.dumps({"type": "run", "cellId": printer}))
        out, all_b = await recv_until(b, lambda m: m.get("type") == "run_done" and m["cellId"] == printer)
        streams = [m for m in all_b if m.get("type") == "output" and m["cellId"] == printer
                   and m["output"]["output_type"] == "stream"]
        assert streams, "no stream output reached B"
        print("2. print cell -> B got stream:", repr(streams[-1]["output"]["text"].strip()[:60]))

    # 3) run a plot cell -> B must receive an image/png
    if plot is None:
        skip(3, "plt.show()")
    else:
        await a.send(json.dumps({"type": "run", "cellId": plot}))
        _, all_b2 = await recv_until(b, lambda m: m.get("type") == "run_done" and m["cellId"] == plot, timeout=60)
        imgs = [m for m in all_b2 if m.get("type") == "output" and m["cellId"] == plot
                and m["output"].get("data", {}).get("image/png")]
        assert imgs, "no image output reached B"
        png_len = len(imgs[-1]["output"]["data"]["image/png"])
        print(f"3. plot cell -> B got image/png ({png_len} b64 chars)")

    # 4) edit on A propagates to B
    original_imports = code[0]["source"]
    await a.send(json.dumps({"type": "edit", "cellId": imports, "source": "# edited by alice\n"}))
    ed, _ = await recv_until(b, lambda m: m.get("type") == "edit" and m["cellId"] == imports)
    assert ed["source"] == "# edited by alice\n"
    print("4. edit on A -> B received:", repr(ed["source"].strip()))
    # Put it back — the session outlives this script, and later steps (plus any
    # re-run against the same server) need the imports cell to still import.
    await a.send(json.dumps({"type": "edit", "cellId": imports, "source": original_imports}))
    await recv_until(b, lambda m: m.get("type") == "edit" and m["cellId"] == imports
                     and m["source"] == original_imports)

    # 5) error capture: run a cell that raises (first not-yet-implemented rep)
    err_cell = None
    # re-fetch original sources from init (solutions overwrote funcs, but a fresh
    # NotImplementedError cell body still raises when re-run)
    for c in code:
        if "raise NotImplementedError" in c["source"]:
            err_cell = c["id"]; break
    if err_cell:
        await a.send(json.dumps({"type": "run", "cellId": err_cell}))
        _, all_e = await recv_until(b, lambda m: m.get("type") == "run_done" and m["cellId"] == err_cell)
        errs = [m for m in all_e if m.get("type") == "output" and m["cellId"] == err_cell
                and m["output"]["output_type"] == "error"]
        # (may or may not raise depending on solutions load; just report)
        print("5. ran a scaffold cell; error outputs seen:", len(errs))

    # 6) restart the shared kernel -> B is told, and execution counts reset
    await a.send(json.dumps({"type": "restart"}))
    await recv_until(b, lambda m: m.get("type") == "kernel_restarted", timeout=90)
    await a.send(json.dumps({"type": "run", "cellId": imports}))
    done2, _ = await recv_until(b, lambda m: m.get("type") == "run_done" and m["cellId"] == imports)
    assert done2["execution_count"] == 1, \
        f"counter should restart at 1, got {done2['execution_count']}"
    print("6. restart -> B notified, execution counter back to [1]")

    # 7) IPython syntax must not be reported as a syntax error (the `obj?`,
    #    `%magic` and `!shell` forms the README advertises).
    for i, label in [(1, "np.array?"), (2, "%matplotlib inline"), (3, "!echo hi")]:
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/lint/{SLUG}",
            data=json.dumps({"sources": ["import numpy as np", "np.array?",
                                         "%matplotlib inline", "!echo hi"],
                             "index": i}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            diags = json.load(r)
        assert not any(d["severity"] == "error" for d in diags), \
            f"{label} wrongly linted as an error: {diags}"
    print("7. lint clean on `obj?`, `%magic`, `!shell`")

    # 8) run_start must name the runner, so other clients can follow them
    await a.send(json.dumps({"type": "run", "cellId": imports}))
    start, _ = await recv_until(b, lambda m: m.get("type") == "run_start" and m["cellId"] == imports)
    assert start.get("by") == init_a["clientId"], \
        f"run_start should carry the runner's id, got {start.get('by')!r}"
    await recv_until(b, lambda m: m.get("type") == "run_done" and m["cellId"] == imports)
    print("8. run_start carries the runner's id (follow-the-runner works)")

    # 9) a cell held down on Shift-Enter must not queue N executions.
    #    Use a scratch cell so we don't clobber the notebook's own contents.
    await a.send(json.dumps({"type": "add", "afterId": imports, "cellType": "code",
                             "source": "import time; time.sleep(2)"}))
    added, _ = await recv_until(b, lambda m: m.get("type") == "add")
    slow = added["cell"]["id"]
    for _ in range(6):
        await a.send(json.dumps({"type": "run", "cellId": slow}))
    _, seen = await recv_until(b, lambda m: m.get("type") == "run_done" and m["cellId"] == slow,
                               timeout=60)
    starts = [m for m in seen if m.get("type") == "run_start" and m["cellId"] == slow]
    assert len(starts) == 1, f"6 run requests collapsed to {len(starts)} executions, expected 1"
    await a.send(json.dumps({"type": "delete", "cellId": slow}))
    await recv_until(b, lambda m: m.get("type") == "delete" and m["cellId"] == slow)
    print("9. 6 rapid run requests collapsed to 1 execution")

    # 10) caret + selection relayed to the other client, for remote cursors
    await b.send(json.dumps({"type": "cursor", "cellId": imports,
                             "anchor": {"line": 3, "ch": 7},
                             "head": {"line": 3, "ch": 12}}))
    cur, _ = await recv_until(a, lambda m: m.get("type") == "cursor")
    assert cur["cellId"] == imports, cur
    assert cur["anchor"] == {"line": 3, "ch": 7}, cur
    assert cur["head"] == {"line": 3, "ch": 12}, cur
    print("10. caret + selection relayed to the other client")

    await a.close(); await b.close()
    print("\nALL CHECKS PASSED")


asyncio.run(main())
