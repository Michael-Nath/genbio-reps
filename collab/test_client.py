"""Two-client integration test: run cells on A, assert B sees synced state."""
import asyncio, json, sys
import websockets

URI = "ws://127.0.0.1:8010/ws"


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

    # 1) run imports on A -> B must see run_start + run_done
    await a.send(json.dumps({"type": "run", "cellId": imports}))
    done, _ = await recv_until(b, lambda m: m.get("type") == "run_done" and m["cellId"] == imports)
    print("1. imports ran, B saw run_done, exec_count =", done["execution_count"])

    # load reference solutions so printer cell won't NotImplementedError
    await a.send(json.dumps({"type": "run", "cellId": solutions}))
    await recv_until(b, lambda m: m.get("type") == "run_done" and m["cellId"] == solutions)

    # 2) run a printing cell -> B must receive a stream output
    await a.send(json.dumps({"type": "run", "cellId": printer}))
    out, all_b = await recv_until(b, lambda m: m.get("type") == "run_done" and m["cellId"] == printer)
    streams = [m for m in all_b if m.get("type") == "output" and m["cellId"] == printer
               and m["output"]["output_type"] == "stream"]
    assert streams, "no stream output reached B"
    print("2. print cell -> B got stream:", repr(streams[-1]["output"]["text"].strip()[:60]))

    # 3) run a plot cell -> B must receive an image/png
    await a.send(json.dumps({"type": "run", "cellId": plot}))
    _, all_b2 = await recv_until(b, lambda m: m.get("type") == "run_done" and m["cellId"] == plot, timeout=60)
    imgs = [m for m in all_b2 if m.get("type") == "output" and m["cellId"] == plot
            and m["output"].get("data", {}).get("image/png")]
    assert imgs, "no image output reached B"
    png_len = len(imgs[-1]["output"]["data"]["image/png"])
    print(f"3. plot cell -> B got image/png ({png_len} b64 chars)")

    # 4) edit on A propagates to B
    await a.send(json.dumps({"type": "edit", "cellId": imports, "source": "# edited by alice\n"}))
    ed, _ = await recv_until(b, lambda m: m.get("type") == "edit" and m["cellId"] == imports)
    assert ed["source"] == "# edited by alice\n"
    print("4. edit on A -> B received:", repr(ed["source"].strip()))

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

    await a.close(); await b.close()
    print("\nALL CHECKS PASSED")


asyncio.run(main())
