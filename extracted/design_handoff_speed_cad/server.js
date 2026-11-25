// Run: ADMIN_KEY=secret node server.js   (Node 16+, no dependencies)  ->  http://localhost:3000
const http = require('http'), fs = require('fs'), path = require('path'), crypto = require('crypto');
const PORT = process.env.PORT || 3000, KEY = process.env.ADMIN_KEY || 'admin';
const DIR = __dirname, DATA = path.join(DIR, 'data'), IMG = path.join(DATA, 'img'), FILE = path.join(DATA, 'state.json');
fs.mkdirSync(IMG, { recursive: true });
const newRound = (n) => ({ id: crypto.randomBytes(4).toString('hex'), name: 'Round ' + n, dur: 20, tol: 1, parts: [{ img: null, ans: '' }], startAt: null, stopAt: null });
let S = fs.existsSync(FILE) ? JSON.parse(fs.readFileSync(FILE)) : { rounds: [newRound(1)], cur: 0, subs: [], out: [] };
const save = () => fs.writeFileSync(FILE, JSON.stringify(S));
const cur = () => S.rounds[S.cur];
const status = (r) => !r.startAt ? 'waiting' : (!r.stopAt && Date.now() < r.startAt + r.dur * 60000) ? 'running' : 'ended';
const board = (r) => {
  const by = {};
  S.subs.filter(s => s.round === r.id && s.ok).forEach(s => { const u = by[s.name] = by[s.name] || { name: s.name, parts: new Set(), t: 0 }; if (!u.parts.has(s.part)) { u.parts.add(s.part); u.t = Math.max(u.t, s.t); } });
  const act = Object.values(by).map(u => ({ name: u.name, parts: u.parts.size, t: u.t })).sort((a, b) => b.parts - a.parts || a.t - b.t);
  return act;
};
const pub = () => {
  const r = cur(), st = status(r);
  return { now: Date.now(), round: { name: r.name, no: S.cur + 1, total: S.rounds.length, dur: r.dur, startAt: r.startAt, stopAt: r.stopAt, status: st, imgs: st === 'waiting' ? [] : r.parts.map(p => p.img ? '/img/' + p.img : null), nParts: r.parts.length }, board: board(r).map(u => ({ ...u, out: S.out.includes(u.name) })), out: S.out };
};
const json = (res, o, c = 200) => { res.writeHead(c, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o)); };
const body = (req) => new Promise(ok => { const c = []; req.on('data', d => c.push(d)); req.on('end', () => ok(Buffer.concat(c))); });
const find = (id) => S.rounds.find(r => r.id === id);
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.pdf': 'application/pdf' };

http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://x'), p = u.pathname;
  try {
    if (p === '/api/state') return json(res, pub());
    if (p === '/api/submit' && req.method === 'POST') {
      const { name, part, mass } = JSON.parse((await body(req)).toString() || '{}');
      const r = cur(), n = String(name || '').trim().slice(0, 40), m = parseFloat(mass), pt = r.parts[(+part) - 1];
      if (!n || !pt || isNaN(m)) return json(res, { msg: 'Enter name, valid part number and mass.' });
      if (status(r) !== 'running') return json(res, { msg: 'Round is not running.' });
      if (S.out.includes(n)) return json(res, { msg: 'You have been eliminated.' });
      const a = parseFloat(pt.ans); if (isNaN(a)) return json(res, { msg: 'No answer set for this part.' });
      const ok = Math.abs(m - a) <= a * r.tol / 100;
      if (ok && S.subs.some(s => s.round === r.id && s.name === n && s.part === +part && s.ok)) return json(res, { msg: 'Part ' + part + ' already counted.' });
      S.subs.push({ round: r.id, name: n, part: +part, ok, t: Date.now() - r.startAt }); save();
      return json(res, { msg: 'Part ' + part + ': ' + (ok ? 'correct.' : 'incorrect.') });
    }
    if (p.startsWith('/img/')) {
      const f = path.join(IMG, path.basename(p));
      if (!fs.existsSync(f)) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' }); return fs.createReadStream(f).pipe(res);
    }
    if (p.startsWith('/api/admin')) {
      if (req.headers['x-admin-key'] !== KEY) return json(res, { error: 'bad key' }, 401);
      if (p === '/api/admin' && req.method === 'GET') return json(res, { ...S, pub: pub() });
      if (p === '/api/admin/img') {
        const r = find(u.searchParams.get('id')), i = +u.searchParams.get('part'), ext = path.extname(u.searchParams.get('f') || '.png').toLowerCase().replace(/[^.a-z0-9]/g, '') || '.png';
        if (!r || !r.parts[i]) return json(res, { error: 'no part' }, 400);
        const fn = crypto.randomBytes(8).toString('hex') + ext; fs.writeFileSync(path.join(IMG, fn), await body(req));
        r.parts[i].img = fn; save(); return json(res, { ok: 1 });
      }
      const a = JSON.parse((await body(req)).toString() || '{}'), r = find(a.id) || cur();
      switch (a.action) {
        case 'addRound': S.rounds.push(newRound(S.rounds.length + 1)); S.cur = S.rounds.length - 1; break;
        case 'delRound': if (S.rounds.length > 1) { S.rounds = S.rounds.filter(x => x.id !== a.id); S.cur = Math.min(S.cur, S.rounds.length - 1); } break;
        case 'select': S.cur = Math.max(0, S.rounds.findIndex(x => x.id === a.id)); break;
        case 'setRound': r.name = a.name ?? r.name; if (a.dur > 0) r.dur = +a.dur; if (a.tol >= 0) r.tol = +a.tol; break;
        case 'addPart': r.parts.push({ img: null, ans: '' }); break;
        case 'delPart': if (r.parts.length > 1) r.parts.splice(a.part, 1); break;
        case 'setAns': r.parts[a.part].ans = a.ans; break;
        case 'start': r.startAt = Date.now(); r.stopAt = null; break;
        case 'stop': r.stopAt = Date.now(); break;
        case 'reset': r.startAt = null; r.stopAt = null; S.subs = S.subs.filter(s => s.round !== r.id); break;
        case 'eliminate': { const act = board(r).filter(x => !S.out.includes(x.name)); act.slice(act.length - Math.floor(act.length / 2)).forEach(x => S.out.push(x.name)); break; }
        case 'restore': S.out = S.out.filter(n => n !== a.name); break;
        case 'clearAll': S.subs = []; S.out = []; S.rounds.forEach(x => { x.startAt = null; x.stopAt = null; }); S.cur = 0; break;
      }
      save(); return json(res, { ...S, pub: pub() });
    }
    let f = p === '/' ? 'Speed CAD.dc.html' : decodeURIComponent(p.slice(1));
    f = path.join(DIR, f);
    if (!f.startsWith(DIR) || f.startsWith(DATA) || path.basename(f) === 'server.js' || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end('Not found'); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'text/html' }); fs.createReadStream(f).pipe(res);
  } catch (e) { json(res, { error: String(e) }, 500); }
}).listen(PORT, () => console.log('Speed CAD on http://localhost:' + PORT + '  admin key: ' + KEY));
