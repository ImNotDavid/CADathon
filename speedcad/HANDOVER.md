# Handover: ICRS Speed CAD Competition site

For an agent picking this up on a Linux machine. Read this, then `README.md` (deploy steps), then `app.py` and
`static/index.html` (the whole app is those two files).

## What it is

A small website for the ICRS Speed CAD Competition. Competitors get a 2D drawing (PDF) of a part, model it in CAD, apply
the material, and submit the part's mass. A correct mass earns points. The organiser runs timed rounds.

Deliberately plain: black on white, monospace, default form controls. No framework, no build step.

## Current rules (as decided by the owner — these changed over time, so trust this list over older notes)

- **Rounds** are timed sessions (default 20 min). The organiser creates rounds, adds parts, uploads one PDF per part, sets
  the correct mass, and picks a difficulty: **Easy = 1 point, Medium = 2, Hard = 3**.
- **Correct** if `|mass - answer| <= |answer| * tol / 100` (tolerance per round, default 1%).
- **Parts in order:** within a round a competitor always works on their first unpassed part. They only ever see that one
  drawing, and the server picks the part for a submission (there is no part-number field).
- **Wrong-guess cooldown:** after a wrong mass, 15 s before that competitor can retry the same part (`COOLDOWN` env var).
- **Scores persist across rounds.** Leaderboard = sum of points over every round, ties broken by who reached the score
  first (wall-clock time of their last correct part). Changing a part's difficulty later recalculates the board.
- **No elimination** (removed on purpose). **No special final-two logic** (done manually by the organiser).
- **Identity is tied to the browser session.** The server sets an HttpOnly cookie `cad_sid`. A competitor registers a
  name once; it's then locked to that browser and nobody else can take it (case/whitespace-insensitive). The organiser can
  **Release** a name so it can be re-registered elsewhere; progress is kept because scores are keyed by name.
- **PDF access is gated:** `/pdf/<file>` is served only to a session currently on that part, or a session that has
  authenticated as organiser. Everyone else gets 403.

## Organiser controls

Admin key (env `ADMIN_KEY`) sent as header `x-admin-key`; the page stores it in `localStorage` (`cad_key`).
Buttons: Start current round · Stop · Reset round (timer + that round's points) · Reset all scores (keeps rounds, PDFs,
names) · Add round · Clear everything (full wipe incl. PDFs and names). Per round: select, rename, duration, tolerance,
delete. Per part: PDF upload, mass, difficulty, remove. Registered competitors list with Release.

## Code layout

```
speedcad/
  app.py            Flask app: all routes, SQLite storage, rules
  static/index.html Single page, vanilla JS, polls /api/state every 1.5 s
  requirements.txt  flask==3.1.0, waitress==3.0.2
  Dockerfile        python:3.12-slim, non-root, waitress on 0.0.0.0:3000, trusts X-Forwarded-* headers
  compose.yaml      service "speedcad", alias "icrs-speedcad" on external network shared-tunnel, volume speedcad-data
  .env.example      ADMIN_KEY, COOLDOWN
  README.md         Deploy / operate instructions for the server
  data/             LOCAL dev data from the owner's Windows machine (cad.db, pdf/). Not part of the code; ignored by Docker.
```

The original design reference (`Speed CAD.dc.html`, a Node `server.js`) lives one level up in
`../extracted/design_handoff_speed_cad/`. It is historical; the rules above supersede it.

### Storage (`DATA_DIR`, default `./data`; `/data` in the container)

- `cad.db` (SQLite, autocommit, one shared connection guarded by a global `threading.RLock` — keep all DB access under
  `lock`):
  - `kv` — one row `state`: JSON `{rounds:[{id,name,dur,tol,parts:[{pdf,ans,diff}],startAt,stopAt}], cur}`
  - `subs` — every submission `(round, name=normalised key, disp, part (1-based), ok, t ms since start, at epoch s)`
  - `players` — `(sid, name UNIQUE, disp, at)` session ↔ claimed name
  - `admins` — sids that have presented the admin key (allowed to open any PDF)
- `pdf/` — uploaded PDFs with random 16-hex filenames.
- `load()` migrates old state: drops the removed `out` (elimination) key, defaults missing `diff` to 1.

### API

- `GET /api/state` → `{now, board:[{name,points,parts,at}], round:{name,no,total,dur,startAt,stopAt,status,nParts}, me?}`;
  `me = {name, part, diff, diffName, pdf}` only when this session has registered.
- `POST /api/join {name}` — claim a name for this session.
- `POST /api/submit {mass}` — submit for the session's current part.
- `GET /pdf/<file>` — gated as above.
- `GET /api/admin` (key) → full state + `players` + `diffs`.
- `POST /api/admin/pdf?id=<round>&part=<0-based>` (key), raw PDF body (must start with `%PDF`, max 50 MB).
- `POST /api/admin {action, id?, part? (0-based), ...}` (key): `addRound, delRound, select, setRound{name,dur,tol},
  addPart, delPart, setAns{ans}, setDiff{diff}, start, stop, reset, resetScores, release{name}, clearAll`.
  Note: requests are sent without a JSON content type, so the server uses `get_json(force=True)`. Keep that.

### Frontend notes (bugs already fixed — don't reintroduce)

- The organiser panel only re-renders when its data signature changes, and not while a text input inside it has focus.
  Rebuilding it every poll previously broke PDF uploads (the file input was replaced while the picker was open) and made
  buttons feel laggy.
- File inputs get their own `change` listener with round id / part captured, so an upload still works if a redraw happens.
- Stale poll responses are dropped via sequence counters.
- The PDF iframe uses `#toolbar=0&navpanes=0&scrollbar=0&view=Fit` and is only rebuilt when the part/PDF changes.

## Running and testing on Linux

```bash
cd speedcad
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
ADMIN_KEY=secret python app.py                       # Flask dev server, http://localhost:3000
# or the production server, as the container runs it:
ADMIN_KEY=secret waitress-serve --host=0.0.0.0 --port=3000 app:app
```

**Test against a throwaway data dir, never the real one:** `DATA_DIR=$(mktemp -d) ADMIN_KEY=k PORT=3001 python app.py`.
An earlier test wrote into live data by mistake. Simulate several browsers with separate cookie jars (e.g. Python
`http.cookiejar` or `curl -c/-b`). There is no automated test suite yet. Things worth covering: registration conflicts,
part ordering, cooldown, points/tie-break across rounds, PDF gating (403 for others), reset/resetScores/clearAll, release.

Behind a proxy, requests with `X-Forwarded-Proto: https` get a `Secure` cookie; a plain-HTTP test client then won't send it
back. Leave that header off in local functional tests.

## Docker / deployment status

- Target: the owner's server, behind an existing Cloudflare tunnel. Follow `README.md`. Hard rules from the server's guide:
  no published ports, listen on `0.0.0.0`, unique alias on `shared-tunnel`, **never create/remove/recreate the
  `shared-tunnel` network, never run `docker network prune` or `docker compose down -v`, never touch the `cloudflared`
  container.** If `shared-tunnel` is missing, ask the owner.
- Tunnel route to request from the owner: hostname e.g. `speedcad.icrobotics.co.uk`, Service URL `http://icrs-speedcad:3000`.
- **The image has never been built.** Docker Desktop on the Windows machine wouldn't start. App behaviour under waitress
  (secure cookie via proxy headers, 413 upload message, full competitor flow) was verified without Docker. First job:
  ```bash
  docker build -t speedcad-test .
  docker network create speedcad-testnet
  docker volume create speedcad-testdata
  docker run -d --name speedcad-test --network speedcad-testnet --network-alias icrs-speedcad \
    -e ADMIN_KEY=k -v speedcad-testdata:/data speedcad-test
  docker run --rm --network speedcad-testnet curlimages/curl -sS -o /dev/null -w "%{http_code}\n" http://icrs-speedcad:3000/
  docker inspect --format '{{.State.Health.Status}}' speedcad-test     # healthy after ~30 s
  # check: non-root user can write /data, data survives `docker restart speedcad-test`
  docker rm -f speedcad-test && docker volume rm speedcad-testdata && docker network rm speedcad-testnet
  ```
  Use your own test network as above, not a local `shared-tunnel`.

## Known gaps / ideas

- Whoever registers a name first owns it; squatting is fixed by the organiser's Release button.
- Two competitors in one browser share a session (use separate browsers / private windows).
- The admin key is a single shared secret with no rate limiting on wrong guesses.
- Deleting a part renumbers later parts' submissions; deleting a round deletes its submissions and PDFs.
- No restore of eliminated players needed any more; the old `restore` action was removed with elimination.
- Polling, not websockets — fine for a club-sized event (~50 competitors ≈ 35 req/s, all tiny).

## Working with the owner

- Not a git repo yet. Ask before `git init`/committing, and never commit `.env` or `data/`.
- The owner prefers being asked questions through the structured question tool when there are real choices.
- The owner changes rules as they go; confirm rule changes against this file and update it when they change.
