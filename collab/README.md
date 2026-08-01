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
You both open it, pick a notebook from the session list, type a name, and
you're in the same notebook. Ctrl-C to stop.

Run on a different port:
```bash
./share.sh 8000
```

## Local only (same machine / LAN, no tunnel)

```bash
./run.sh                # http://localhost:8000
```

## Sessions

Every `.ipynb` under the repo is auto-discovered and served as its own
session — own cells, own live kernel, own autosave sidecar. Open `/` to see
all of them at a glance:

- a live dot + connected-user count if people are in it right now
- "kernel running · idle" if the kernel has started but nobody's connected
- "saved" if there's autosaved work waiting, kernel not started yet
- "not started" for a notebook nobody's opened yet

Click **Open →** on any card (or go straight to `/n/<slug>`) to join that
notebook's live session. Kernels start lazily — the first person to open a
notebook spins up its kernel; it's shared by everyone who joins after.

## What you get

- **Real editor** — CodeMirror with Python syntax highlighting, line numbers,
  bracket matching/closing, and 4-space auto-indent.
- **Live Python linting** — `pyflakes` runs on the backend as you type
  (undefined names, unused imports, syntax errors) with squiggles + gutter marks.
  Cross-cell names are understood, so `np` defined in an earlier cell isn't
  flagged in a later one. Cells go through IPython's own input transformer
  first, so `np.array?`, `%timeit`, and `!pip install` are linted as the Python
  they actually become — not reported as syntax errors.
- **Jupyter keyboard model** — command mode (blue) vs edit mode (green):
  - `Esc` command · `Enter` edit
  - `A`/`B` insert above/below · `D` `D` delete · `M`/`Y` markdown/code
  - `J`/`K` (or arrows) move selection · `C`/`X`/`V` copy/cut/paste cell
  - `Shift-Enter` run + next · `Ctrl/Cmd-Enter` run · `Alt-Enter` run + insert
  - `Cmd//Ctrl-/` toggle comment · `Tab`/`Shift-Tab` indent
- **Live cell editing** — typing syncs to your partner (~90ms debounce). Incoming
  text is applied as a minimal patch to just the run of characters that changed,
  so it lands *while you're typing* without moving your caret or re-rendering the
  cell. (It used to be skipped entirely whenever you had the cell focused, which
  left the two of you silently out of sync.)
- **Sharing a cell is safe** — you see your partner's caret inside the editor in
  their colour, and the cell turns amber with a "both editing" tag when you're
  both in it. Same-*region* edits are still last-write-wins, so the caret is what
  keeps you off each other's lines.
- **Follow the runner** — when your partner hits Shift-Enter, their cell scrolls
  into view for you too and pulses, so you're both watching the same execution.
  Toggle it off with the **follow** checkbox in the header; it never steals your
  caret while you're mid-edit.
- **Shared execution** — outputs stream to everyone: text, matplotlib images,
  and tracebacks, all from one shared kernel. Consecutive stdout/stderr chunks
  merge into one output the way Jupyter does, so a training loop printing
  thousands of lines stays one block (the last ~200k chars are kept).
- **Inline docs (`?` / `??`)** — end a line with `obj?` for the signature +
  docstring, or `obj??` for the source (e.g. `np.array?`, `tilted_resample??`).
  Works just like Jupyter (rendered from IPython's help "page" payload).
- **Run all / Interrupt / Restart kernel** and **Save to .ipynb** (writes cells +
  outputs back to the real notebook, so your progress is committable). Interrupt
  abandons the rest of a Run all instead of ploughing on to the next cell;
  Restart clears the shared namespace for everyone (cells and outputs survive).
- **Presence** — who's connected, and where their cursor is.

## Persistence (survives restarts)

Live state — every cell's source, type, and **outputs** — is autosaved per
notebook (debounced ~1.2s, and after every run) to a gitignored sidecar at
`collab/.state/<slug>.autosave.ipynb` (slug = the full path, so two notebooks
with the same filename in different folders keep separate state). On startup the server restores each
session from its sidecar if one exists, so **restarting the server resumes
exactly where you left off**, for every notebook. Browser reloads never lose
state (the server holds it).

- The **pristine notebook is only touched by the 💾 Save button** — autosave goes
  to the sidecar, so your teaching notebook stays clean until you choose to commit.
- **Start fresh** from the original notebook: stop the server and
  `rm -rf collab/.state`.
- Caveat: cell content + outputs persist, but **live kernel variables do not**
  survive a restart — hit **Run all** to rebuild them.
- Notebooks added to the repo while the server is running are picked up on the
  next session-list refresh; no restart needed.

## How it works

- `server.py` — FastAPI. Discovers every `.ipynb` in the repo as its own
  `Session` (cells, kernel, clients, autosave). Each session runs code against
  its own `AsyncKernelManager` kernel (started lazily on first connection) and
  broadcasts edits/outputs/presence over `/ws/<slug>`. `%matplotlib inline` is
  enabled per-kernel so figures render as PNGs. `GET /api/sessions` reports
  live status for the session list.
- `static/sessions.html` — the `/` landing page: lists every session with its
  status (live / kernel idle / saved / not started), polling `/api/sessions`
  every few seconds.
- `static/notebook.html` — zero-build vanilla JS notebook UI, served at
  `/n/<slug>`. Renders cells, syncs edits, streams outputs, renders markdown
  (marked.js).
- `share.sh` — server + `cloudflared` quick tunnel (binary auto-downloaded to
  `.bin/`, which is gitignored).
- `test_client.py` — two-client integration test: connects A and B, runs cells
  on A, and asserts B sees the streams, images, edits, and kernel restarts.
  Start the server, then `.venv/bin/python test_client.py [port] [slug]`
  (defaults: port 8000, first session the server reports).

## Notes / caveats

- One shared kernel = one shared namespace. Great for pairing; if you both hit Run
  at once, executions queue (a lock serializes them). Repeat requests for a cell
  that's already running are dropped rather than queued, so leaning on
  Shift-Enter can't stack up a dozen executions.
- The trycloudflare URL is ephemeral — a new one each run. Fine for a session.
- Edits are last-write-wins per cell (no OT/CRDT), but they converge: the server
  serializes edits and every client applies the same latest text, so you can't
  drift apart. What you can still lose is a keystroke typed inside the ~90ms
  send window while your partner's version lands on the *same* lines. Different
  lines of the same cell are fine — watch their caret and you'll be fine.
- Anyone with the URL can run code on your machine. Only share with your friend,
  and stop the tunnel when done.
