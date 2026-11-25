# Handoff: ICRS Speed CAD Competition Site

## Overview
A bare-bones, function-only site for the ICRS Speed CAD Competition (https://icrobotics.co.uk/icrs-speed-cad-competition/). No theming by design.

Competition rules (from the event page): everyone gets the same 2D drawings and a 20 minute timer. Competitors model each part, apply the material shown, and submit its mass. A correct mass counts as one part. At time, rank by most parts, with time taken as tiebreaker. The bottom half (rounded down) is eliminated. Repeat until two remain; they race on one part and the first correct mass wins.

## About the Design Files
`Speed CAD.dc.html` and `server.js` are **design/behavior references**, not production code to copy. Recreate them in the target codebase's existing environment (React, Vue, etc.). If none exists, pick a simple stack (e.g. Node + any lightweight frontend). `server.js` is a working zero-dependency Node reference for the backend contract and can be ported or reused. `support.js` is only the runtime for the HTML prototype; ignore it.

## Fidelity
**Low-fidelity.** Plain black-on-white, monospace, 1–2px black borders, default form controls. Match structure and function; apply the target codebase's styling if it has one.

## Screens / Views
Single page, max-width 900px, 16px padding, `font-family: monospace`, black on white. Top to bottom:

1. **Header**: h1 "ICRS Speed CAD Competition" (20px). Line below: round label ("Round 1 (1/3)") and an "Organiser" toggle button.
2. **Timer box**: 2px black border, 12px padding. Status text ("Waiting for start" / "Running" / "Time up" / "Connecting...") above a 72px bold `mm:ss` countdown.
3. **Organiser panel** (hidden until toggled; 2px border):
   - Admin key password input (stored in localStorage `cad_key`); "Wrong key" on 401.
   - Buttons: Start current round, Stop, Reset round (confirm; clears that round's scores), Eliminate bottom half (confirm).
   - Rounds list: each round has a Select button, name input, duration (min), tolerance (%), Delete round; selected round is highlighted `#eee`. Under each round: parts, each with file input (image/PDF), "[image set]/[no image]" label, correct mass (g) input, Remove; plus Add part.
   - Add round, Clear everything (confirm), and an "Eliminated:" list.
4. **Submit mass**: inputs name, part #, mass (g), Submit button. Result message line below.
5. **Scores table**: columns #, Name, Parts, Last correct (mm:ss). Eliminated competitors are grey with " (eliminated)".
6. **Drawings**: one image per part labelled "Part N", click opens full size in a new tab. Before the round starts shows "Drawings appear when the round starts."

## Interactions & Behavior
- Client polls `GET /api/state` every 1.5s. Timer ticks every 250ms locally using a server clock offset (`serverNow - Date.now()`), so all screens agree.
- Submit: `POST /api/submit {name, part, mass}` returns `{msg}`. Show msg; clear part and mass fields.
- Organiser actions `POST /api/admin` with header `x-admin-key`; the organiser view polls `GET /api/admin` while open.
- Rules enforced server-side: round must be running (started, not stopped, within duration); eliminated names rejected; a part counts once per name; correct if `|m - ans| <= ans * tol/100` (default tol 1%); a part with no answer set is rejected.
- Ranking: parts correct (desc), then time of the last correct submission (asc).
- Elimination: of active (non-eliminated) competitors in the current round's ranking, the bottom `floor(n/2)` are added to `out`.
- Final (two remain): make a round with 1 part; top of the board is whoever submitted correctly first.
- Drawings URLs are withheld from the public state until the round starts. Correct answers are never sent to the public endpoint.

## State Management
Server (persisted to `data/state.json`; images in `data/img/`):
```
{ rounds:[{id,name,dur(min),tol(%),parts:[{img,ans}],startAt,stopAt}], cur:int, subs:[{round,name,part,ok,t(ms since start)}], out:[names] }
```
Client: name/part/mass inputs, message, public state + clock offset, showAdmin, admin key, admin state.

### API
- `GET /api/state` → `{now, round:{name,no,total,dur,startAt,stopAt,status,imgs[],nParts}, board:[{name,parts,t,out}], out}`
- `POST /api/submit`
- `GET /api/admin` → full state (key required)
- `POST /api/admin` actions: addRound, delRound, select, setRound{name,dur,tol}, addPart, delPart, setAns{part,ans}, start, stop, reset, eliminate, restore, clearAll
- `POST /api/admin/img?id=&part=&f=filename` raw body = file
- `GET /img/<file>`

## Known gaps / suggestions for production
- Names are unauthenticated (anyone can use any name); consider per-competitor codes.
- Admin key is a single shared secret over plain HTTP; serve behind HTTPS.
- No UI for `restore` action (API exists).
- Polling rather than websockets; fine for a small event.

## Design Tokens
Colors: `#000` text/borders, `#fff` background, `#eee` selected round, `#777` eliminated rows. Type: monospace; 72px timer, 20px h1, 16px h2. Spacing: 8/12/16px. No radius, no shadows.

## Assets
None. Drawings are uploaded by the organiser.

## Files
- `Speed CAD.dc.html` — frontend reference
- `server.js` — backend reference (`ADMIN_KEY=secret node server.js`, port 3000)
- `support.js` — prototype runtime only
