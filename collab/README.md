# collab — live shared notebook

Two+ people open one URL and share a single live notebook: **same cells, same
edits, same outputs, in real time.** Code runs against one shared Jupyter kernel,
so state (variables, plots) is common to everyone. Sync is over WebSocket for low
latency.

## Just the two of us, right now

```bash
cd collab
./share.sh              # runs the server + a public tunnel
```

It prints a `https://<random>.trycloudflare.com` URL. Send it to your friend.
You both open it, type a name, and you're in the same notebook. Ctrl-C to stop.

Run a different notebook / port:
```bash
./share.sh ../00_foundations/01_proteins_as_tensors.ipynb 8000
```

## Local only (same machine / LAN, no tunnel)

```bash
./run.sh                # http://localhost:8000
```

## What you get

- **Real editor** — CodeMirror with Python syntax highlighting, line numbers,
  bracket matching/closing, and 4-space auto-indent.
- **Live Python linting** — `pyflakes` runs on the backend as you type
  (undefined names, unused imports, syntax errors) with squiggles + gutter marks.
  Cross-cell names are understood, so `np` defined in an earlier cell isn't
  flagged in a later one.
- **Jupyter keyboard model** — command mode (blue) vs edit mode (green):
  - `Esc` command · `Enter` edit
  - `A`/`B` insert above/below · `D` `D` delete · `M`/`Y` markdown/code
  - `J`/`K` (or arrows) move selection · `C`/`X`/`V` copy/cut/paste cell
  - `Shift-Enter` run + next · `Ctrl/Cmd-Enter` run · `Alt-Enter` run + insert
  - `Cmd//Ctrl-/` toggle comment · `Tab`/`Shift-Tab` indent
- **Live cell editing** — typing syncs to your partner (~90ms debounce); the cell
  someone else is in is tagged with their name/color.
- **Shared execution** — outputs stream to everyone: text, matplotlib images,
  and tracebacks, all from one shared kernel.
- **Run all / Interrupt** and **Save to .ipynb** (writes cells + outputs back to
  the file, so your progress is committable).
- **Presence** — who's connected, and where their cursor is.

## How it works

- `server.py` — FastAPI. Loads the `.ipynb`, holds shared cell state, runs code
  against one `AsyncKernelManager` kernel, and broadcasts edits/outputs/presence
  over `/ws`. `%matplotlib inline` is enabled at startup so figures render as PNGs.
- `static/index.html` — zero-build vanilla JS. Renders cells, syncs edits, streams
  outputs, renders markdown (marked.js).
- `share.sh` — server + `cloudflared` quick tunnel (binary auto-downloaded to
  `.bin/`, which is gitignored). `test_client.py` is the integration test.

## Notes / caveats

- One shared kernel = one shared namespace. Great for pairing; if you both hit Run
  at once, executions queue (a lock serializes them).
- The trycloudflare URL is ephemeral — a new one each run. Fine for a session.
- Edits are last-write-wins per cell (no OT/CRDT). Perfect for two people pairing;
  don't type into the *same* cell simultaneously.
- Anyone with the URL can run code on your machine. Only share with your friend,
  and stop the tunnel when done.
