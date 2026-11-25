"""ICRS Speed CAD Competition server.

Local:   ADMIN_KEY=secret python app.py          (Flask dev server, port 3000)
Docker:  see README.md (waitress behind the Cloudflare tunnel)
"""
import json, os, secrets, sqlite3, threading, time
from flask import Flask, jsonify, request, send_from_directory, abort, g

PORT = int(os.environ.get("PORT", 3000))
KEY = os.environ.get("ADMIN_KEY", "admin")
COOLDOWN = float(os.environ.get("COOLDOWN", 15))  # seconds between wrong guesses, per name per part
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DATA_DIR") or os.path.join(HERE, "data")
PDFS = os.path.join(DATA, "pdf")
os.makedirs(PDFS, exist_ok=True)
MAX_UPLOAD_MB = 50  # Cloudflare refuses bodies over 100 MB; stay well under so our own message is shown

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
# Behind the Cloudflare tunnel, waitress itself trusts the X-Forwarded-* headers (see Dockerfile CMD), so
# request.is_secure is true there and the session cookie is marked Secure.
lock = threading.RLock()
db = sqlite3.connect(os.path.join(DATA, "cad.db"), check_same_thread=False, isolation_level=None)
db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
db.execute("""CREATE TABLE IF NOT EXISTS subs (id INTEGER PRIMARY KEY, round TEXT, name TEXT, disp TEXT,
              part INTEGER, ok INTEGER, t INTEGER, at REAL)""")
# one row per browser session that has claimed a competitor name (name = normalised key, unique)
db.execute("""CREATE TABLE IF NOT EXISTS players (sid TEXT PRIMARY KEY, name TEXT UNIQUE, disp TEXT, at REAL)""")
# browser sessions that have authenticated as organiser (lets them open any PDF)
db.execute("CREATE TABLE IF NOT EXISTS admins (sid TEXT PRIMARY KEY)")

COOKIE = "cad_sid"


@app.before_request
def _session():
    sid = request.cookies.get(COOKIE, "")
    g.new_sid = not (len(sid) == 32 and all(c in "0123456789abcdef" for c in sid))
    g.sid = secrets.token_hex(16) if g.new_sid else sid


@app.after_request
def _set_cookie(resp):
    if getattr(g, "new_sid", False):
        resp.set_cookie(COOKIE, g.sid, max_age=60 * 60 * 24 * 30, httponly=True, samesite="Lax",
                        secure=request.is_secure)
    return resp


@app.errorhandler(413)
def _413(e):
    return jsonify(error=f"file too large (max {MAX_UPLOAD_MB} MB)"), 413


def me_player():
    """(key, display name) this browser session has claimed, or (None, None)."""
    with lock:
        r = db.execute("SELECT name, disp FROM players WHERE sid=?", (g.sid,)).fetchone()
    return (r[0], r[1]) if r else (None, None)


DIFF = {1: "Easy", 2: "Medium", 3: "Hard"}  # difficulty -> label; the number is the points it is worth


def new_part():
    return dict(pdf=None, ans="", diff=1)


def new_round(n):
    return dict(id=secrets.token_hex(4), name=f"Round {n}", dur=20, tol=1, parts=[new_part()],
                startAt=None, stopAt=None)


def load():
    r = db.execute("SELECT v FROM kv WHERE k='state'").fetchone()
    if r:
        S = json.loads(r[0])
        S.pop("out", None)  # elimination was removed
        for x in S["rounds"]:
            for p in x["parts"]: p.setdefault("diff", 1)
        return S
    S = dict(rounds=[new_round(1)], cur=0)
    save(S)
    return S


def save(S):
    db.execute("INSERT OR REPLACE INTO kv VALUES('state',?)", (json.dumps(S),))


def now_ms():
    return int(time.time() * 1000)


def status(r):
    if not r["startAt"]:
        return "waiting"
    if not r["stopAt"] and now_ms() < r["startAt"] + r["dur"] * 60000:
        return "running"
    return "ended"


def board(S):
    """Cumulative leaderboard over every round: points (sum of part difficulties), then whoever reached
    that score first (wall-clock time of their last correct part)."""
    worth = {(x["id"], i + 1): p["diff"] for x in S["rounds"] for i, p in enumerate(x["parts"])}
    by = {}
    for rid, name, disp, part, at in db.execute(
            "SELECT round,name,disp,part,at FROM subs WHERE ok=1 ORDER BY id"):
        if (rid, part) not in worth:
            continue
        u = by.setdefault(name, dict(name=disp, key=name, done=set(), points=0, at=0))
        if (rid, part) not in u["done"]:
            u["done"].add((rid, part))
            u["points"] += worth[(rid, part)]
            u["at"] = max(u["at"], at)
    rows = [dict(name=u["name"], key=u["key"], points=u["points"], parts=len(u["done"]), at=int(u["at"] * 1000))
            for u in by.values()]
    rows.sort(key=lambda u: (-u["points"], u["at"]))
    return rows


def name_key(name):
    return " ".join(str(name or "").casefold().split())[:40]


def next_part(r, key):
    """1-based number of the first part this competitor has not yet passed, or None if all done."""
    solved = {p for (p,) in db.execute("SELECT part FROM subs WHERE round=? AND name=? AND ok=1", (r["id"], key))}
    return next((i for i in range(1, len(r["parts"]) + 1) if i not in solved), None)


def current_pdf(S, key):
    """(part number, pdf filename or None) for the drawing this competitor may see right now."""
    r = S["rounds"][S["cur"]]
    if not key or status(r) == "waiting":
        return None, None
    part = next_part(r, key)
    return part, (r["parts"][part - 1]["pdf"] if part else None)


def pub(S, key=None, disp=None):
    r = S["rounds"][S["cur"]]
    st = status(r)
    b = [dict(name=u["name"], points=u["points"], parts=u["parts"], at=u["at"]) for u in board(S)]
    res = dict(now=now_ms(), board=b,
               round=dict(name=r["name"], no=S["cur"] + 1, total=len(S["rounds"]), dur=r["dur"],
                          startAt=r["startAt"], stopAt=r["stopAt"], status=st, nParts=len(r["parts"])))
    if key:
        # only ever reveal the drawing for the part this session's competitor is currently on
        _, pdf = current_pdf(S, key)
        part = next_part(r, key)
        diff = r["parts"][part - 1]["diff"] if part else None
        res["me"] = dict(name=disp, part=part, diff=diff, diffName=DIFF.get(diff),
                         pdf=("/pdf/" + pdf) if pdf else None)
    return res


def need_admin():
    if not secrets.compare_digest(request.headers.get("x-admin-key", ""), KEY):
        abort(401)
    with lock:
        db.execute("INSERT OR IGNORE INTO admins VALUES(?)", (g.sid,))


@app.errorhandler(401)
def _401(e):
    return jsonify(error="bad key"), 401


@app.get("/")
def index():
    resp = send_from_directory(os.path.join(HERE, "static"), "index.html")
    resp.headers["Cache-Control"] = "no-store"  # always serve the latest page
    return resp


def rm_pdf(fn):
    if fn:
        try:
            os.remove(os.path.join(PDFS, fn))
        except OSError:
            pass


def part_index(r, a):
    try:
        i = int(a.get("part"))
    except (TypeError, ValueError):
        return None
    return i if 0 <= i < len(r["parts"]) else None


@app.get("/api/state")
def state():
    with lock:
        return jsonify(pub(load(), *me_player()))


@app.post("/api/join")
def join():
    """Claim a competitor name for this browser session. A name can only belong to one session."""
    d = request.get_json(force=True, silent=True) or {}
    disp = " ".join(str(d.get("name") or "").split())[:40]
    key = name_key(disp)
    with lock:
        mine, mine_disp = me_player()
        if mine:
            return jsonify(ok=mine == key, name=mine_disp,
                           msg=None if mine == key else f"This browser is already registered as {mine_disp}.")
        if not key:
            return jsonify(ok=False, msg="Enter your name.")
        if db.execute("SELECT 1 FROM players WHERE name=?", (key,)).fetchone():
            return jsonify(ok=False, msg="That name is already taken. Ask an organiser if it is yours.")
        db.execute("INSERT INTO players VALUES(?,?,?,?)", (g.sid, key, disp, time.time()))
        return jsonify(ok=True, name=disp)


@app.post("/api/submit")
def submit():
    d = request.get_json(force=True, silent=True) or {}
    try:
        m = float(d.get("mass"))
    except (TypeError, ValueError):
        m = float("nan")
    key, disp = me_player()
    if not key:
        return jsonify(msg="Register your name first.")
    if m != m:
        return jsonify(msg="Enter a mass.")
    with lock:
        S = load()
        r = S["rounds"][S["cur"]]
        if status(r) != "running":
            return jsonify(msg="Round is not running.")
        part = next_part(r, key)  # always the part they are on; they can't skip ahead
        if part is None:
            return jsonify(msg="You have completed every part.")
        try:
            a = float(r["parts"][part - 1]["ans"])
        except ValueError:
            return jsonify(msg="No answer set for this part.")
        last = db.execute("SELECT MAX(at) FROM subs WHERE round=? AND name=? AND part=? AND ok=0",
                          (r["id"], key, part)).fetchone()[0]
        if last and time.time() - last < COOLDOWN:
            wait = int(COOLDOWN - (time.time() - last)) + 1
            return jsonify(msg=f"Part {part}: wait {wait}s before trying again.")
        ok = abs(m - a) <= abs(a) * r["tol"] / 100
        db.execute("INSERT INTO subs(round,name,disp,part,ok,t,at) VALUES(?,?,?,?,?,?,?)",
                   (r["id"], key, disp, part, int(ok), now_ms() - r["startAt"], time.time()))
        if not ok:
            return jsonify(msg=f"Part {part}: incorrect.")
        pts = r["parts"][part - 1]["diff"]
        more = part < len(r["parts"])
        return jsonify(msg=f"Part {part}: correct, +{pts} point{'s' if pts != 1 else ''}. "
                           + (f"Now on part {part + 1}." if more else "All parts in this round complete!"))


@app.get("/pdf/<fn>")
def pdf(fn):
    if not fn.endswith(".pdf") or "/" in fn or "\\" in fn:
        abort(404)
    with lock:
        allowed = db.execute("SELECT 1 FROM admins WHERE sid=?", (g.sid,)).fetchone() is not None
        if not allowed:  # competitors may only open the drawing for the part they are on
            allowed = current_pdf(load(), me_player()[0])[1] == fn
    if not allowed:
        abort(403)
    resp = send_from_directory(PDFS, fn, mimetype="application/pdf")
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


def admin_view(S):
    players = [dict(name=k, disp=d) for k, d in db.execute("SELECT name, disp FROM players ORDER BY at")]
    return dict(rounds=S["rounds"], cur=S["cur"], players=players, diffs=DIFF, pub=pub(S))


@app.get("/api/admin")
def admin_get():
    need_admin()
    with lock:
        return jsonify(admin_view(load()))


@app.post("/api/admin/pdf")
def admin_pdf():
    need_admin()
    body = request.get_data()
    if not body.startswith(b"%PDF"):
        return jsonify(error="not a PDF"), 400
    with lock:
        S = load()
        r = next((x for x in S["rounds"] if x["id"] == request.args.get("id")), None)
        i = request.args.get("part", type=int)
        if not r or i is None or not 0 <= i < len(r["parts"]):
            return jsonify(error="no part"), 400
        os.makedirs(PDFS, exist_ok=True)
        fn = secrets.token_hex(8) + ".pdf"
        with open(os.path.join(PDFS, fn), "wb") as f:
            f.write(body)
        rm_pdf(r["parts"][i]["pdf"])
        r["parts"][i]["pdf"] = fn
        save(S)
    return jsonify(ok=1)


@app.post("/api/admin")
def admin_post():
    need_admin()
    a = request.get_json(force=True, silent=True) or {}
    act = a.get("action")
    with lock:
        S = load()
        r = next((x for x in S["rounds"] if x["id"] == a.get("id")), None) or S["rounds"][S["cur"]]
        if act == "addRound":
            S["rounds"].append(new_round(len(S["rounds"]) + 1)); S["cur"] = len(S["rounds"]) - 1
        elif act == "delRound" and len(S["rounds"]) > 1:
            gone = next((x for x in S["rounds"] if x["id"] == a.get("id")), None)
            if gone:
                cur_id = S["rounds"][S["cur"]]["id"]
                for p in gone["parts"]: rm_pdf(p["pdf"])
                db.execute("DELETE FROM subs WHERE round=?", (gone["id"],))
                S["rounds"].remove(gone)
                S["cur"] = next((i for i, x in enumerate(S["rounds"]) if x["id"] == cur_id), 0)
        elif act == "select":
            S["cur"] = max(0, next((i for i, x in enumerate(S["rounds"]) if x["id"] == a.get("id")), 0))
        elif act == "setRound":
            if a.get("name") is not None: r["name"] = str(a["name"])
            try:
                if float(a.get("dur", 0)) > 0: r["dur"] = float(a["dur"])
            except (TypeError, ValueError): pass
            try:
                if float(a.get("tol", -1)) >= 0: r["tol"] = float(a["tol"])
            except (TypeError, ValueError): pass
        elif act == "addPart":
            r["parts"].append(new_part())
        elif act == "delPart" and len(r["parts"]) > 1 and part_index(r, a) is not None:
            i = part_index(r, a)
            rm_pdf(r["parts"][i]["pdf"])
            del r["parts"][i]
            # part numbers after i shift down by one; keep submissions in step
            db.execute("DELETE FROM subs WHERE round=? AND part=?", (r["id"], i + 1))
            db.execute("UPDATE subs SET part=part-1 WHERE round=? AND part>?", (r["id"], i + 1))
        elif act == "setAns" and part_index(r, a) is not None:
            r["parts"][part_index(r, a)]["ans"] = str(a.get("ans", "")).strip()
        elif act == "setDiff" and part_index(r, a) is not None and str(a.get("diff")) in ("1", "2", "3"):
            r["parts"][part_index(r, a)]["diff"] = int(a["diff"])
        elif act == "start":
            r["startAt"] = now_ms(); r["stopAt"] = None
        elif act == "stop":
            r["stopAt"] = now_ms()
        elif act == "reset":  # restart this round: timer and the points earned in it
            r["startAt"] = None; r["stopAt"] = None
            db.execute("DELETE FROM subs WHERE round=?", (r["id"],))
        elif act == "resetScores":  # zero the leaderboard; rounds, parts, PDFs and names stay
            db.execute("DELETE FROM subs")
        elif act == "release":  # free a name so the competitor can register it again in another browser
            db.execute("DELETE FROM players WHERE name=?", (name_key(a.get("name")),))
        elif act == "clearAll":  # full wipe: rounds, parts, answers, PDFs, scores, names
            db.execute("DELETE FROM subs"); db.execute("DELETE FROM players")
            for x in S["rounds"]:
                for p in x["parts"]: rm_pdf(p["pdf"])
            S = dict(rounds=[new_round(1)], cur=0)
        save(S)
        return jsonify(admin_view(S))


if __name__ == "__main__":
    print(f"Speed CAD on http://0.0.0.0:{PORT}  admin key: {KEY}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
