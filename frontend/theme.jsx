// theme.jsx — shared design system, backend API layer, and atoms for CLIPMAKER.AI
// Aesthetic: high-contrast monochrome, film grain, Kirlian energy, brutalist
// wide type, thin technical reticle overlays. Yellow used as a single sparing accent.

/* ---------- global stylesheet (injected once) ---------- */
const CM_CSS = `
.cm, .cm *{ box-sizing:border-box; }
.cm{
  --bg:#060607; --bg1:#0b0b0d; --bg2:#101013; --bg3:#16161a;
  --line:rgba(255,255,255,.08); --line2:rgba(255,255,255,.16); --line3:rgba(255,255,255,.30);
  --text:#f4f4f5; --muted:#8c8c93; --faint:#56565d;
  --acc:#ffc21a; --acc-dim:rgba(255,194,26,.16);
  --ok:#73e0ad; --bad:#ff5a52;
  --mono:'JetBrains Mono',ui-monospace,monospace;
  --disp:'Archivo',sans-serif;
  font-family:var(--disp);
  color:var(--text);
  background:var(--bg);
  -webkit-font-smoothing:antialiased;
  letter-spacing:.01em;
  position:relative;
}
.cm-grain{ position:absolute; inset:0; pointer-events:none; z-index:60;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.82' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.9'/%3E%3C/svg%3E");
  opacity:.06; mix-blend-mode:overlay; }
.cm-scan{ position:absolute; inset:0; pointer-events:none; z-index:59;
  background:repeating-linear-gradient(180deg,transparent 0 3px,rgba(0,0,0,.22) 3px 4px);
  opacity:.35; mix-blend-mode:multiply; }
.cm-vig{ position:absolute; inset:0; pointer-events:none; z-index:58;
  background:radial-gradient(120% 80% at 50% 20%,transparent 40%,rgba(0,0,0,.55) 100%); }

/* type */
.cm .disp{ font-family:var(--disp); font-weight:800; font-stretch:125%;
  text-transform:uppercase; line-height:.92; letter-spacing:-.01em; }
.cm .mono{ font-family:var(--mono); }
.cm .ovl{ font-family:var(--mono); text-transform:uppercase; letter-spacing:.22em;
  font-size:10px; color:var(--faint); }
.cm .label{ font-family:var(--mono); text-transform:uppercase; letter-spacing:.2em;
  font-size:11px; color:var(--muted); }

/* eye mark */
.cm .eye{ mix-blend-mode:screen; filter:drop-shadow(0 0 14px rgba(255,255,255,.25)); }

/* reticle bits */
.cm .ring{ position:absolute; border:1px solid var(--line2); border-radius:999px; pointer-events:none; }
.cm .tick{ position:absolute; background:var(--line2); pointer-events:none; }

/* status chip */
.cm .chip{ display:inline-flex; align-items:center; gap:7px; font-family:var(--mono);
  text-transform:uppercase; letter-spacing:.16em; font-size:10px; padding:5px 10px;
  border:1px solid var(--line2); border-radius:2px; color:var(--muted); white-space:nowrap; }
.cm .chip .dot{ width:6px; height:6px; border-radius:50%; background:currentColor; }
.cm .chip.ok{ color:var(--ok); border-color:rgba(115,224,173,.3); }
.cm .chip.run{ color:var(--acc); border-color:rgba(255,194,26,.4); }
.cm .chip.q{ color:var(--faint); }

/* buttons */
.cm .btn{ font-family:var(--mono); text-transform:uppercase; letter-spacing:.14em;
  font-size:12px; padding:13px 22px; border:1px solid var(--line2); background:transparent;
  color:var(--text); cursor:pointer; border-radius:2px; transition:.15s; display:inline-flex;
  align-items:center; gap:10px; }
.cm .btn:hover{ border-color:var(--line3); background:rgba(255,255,255,.03); }
.cm .btn.pri{ background:var(--acc); color:#0a0a0a; border-color:var(--acc); font-weight:700; }
.cm .btn.pri:hover{ background:#ffce42; box-shadow:0 0 28px rgba(255,194,26,.35); }
.cm .btn.ghost{ padding:9px 14px; font-size:10px; color:var(--muted); }
.cm .btn.x{ padding:0; width:30px; height:30px; justify-content:center; color:var(--faint); }
.cm .btn.x:hover{ color:var(--bad); border-color:rgba(255,90,82,.4); }

/* panels */
.cm .panel{ background:linear-gradient(180deg,var(--bg1),var(--bg)); border:1px solid var(--line); }
.cm .inp{ width:100%; background:var(--bg); border:1px solid var(--line2); color:var(--text);
  font-family:var(--mono); font-size:13px; padding:14px 16px; border-radius:2px; outline:none; }
.cm .inp::placeholder{ color:var(--faint); }
.cm .inp:focus{ border-color:var(--line3); }

/* keyframes */
@keyframes cm-spin{ to{ transform:rotate(360deg); } }
@keyframes cm-pulse{ 0%,100%{ opacity:.4; } 50%{ opacity:1; } }
@keyframes cm-sweep{ 0%{ transform:translateY(-100%);} 100%{ transform:translateY(400%);} }
.cm .spin{ animation:cm-spin 14s linear infinite; }
.cm .pulse{ animation:cm-pulse 1.8s ease-in-out infinite; }
`;

(function injectCM(){
  if (document.getElementById('cm-theme')) return;
  const s = document.createElement('style'); s.id='cm-theme'; s.textContent = CM_CSS;
  document.head.appendChild(s);
})();

/* ---------- backend API (replaces the old hardcoded mock DATA) ---------- */
const API = {
  health: () => fetch('/api/health').then(r => r.ok).catch(() => false),
  jobs:   () => fetch('/api/jobs').then(r => r.json()),
  clips:  (jobId) => fetch(`/api/jobs/${jobId}/clips`).then(r => r.json()),
  createJob: (source_type, source) => fetch('/api/jobs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_type, source }),
  }),
  approve: (id) => fetch(`/api/clips/${id}/approve`, { method: 'POST' }),
  reject:  (id) => fetch(`/api/clips/${id}/reject`,  { method: 'POST' }),
  cancel:  (id) => fetch(`/api/jobs/${id}/cancel`,   { method: 'POST' }),
};

// Map a backend JobStatus onto the scanning strip's { stage label, progress % }.
// Only the statuses that mean "actively working" appear here — a job with any other
// status (ready/error/cancelled) is not "running" and won't drive the SCANNING bar.
const STAGE = {
  queued:          { label: 'queued',         pct: 4  },
  ingesting:       { label: 'ingesting',      pct: 16 },
  transcribing:    { label: 'transcribing',   pct: 38 },
  finding_moments: { label: 'finding moments', pct: 62 },
  rendering:       { label: 'rendering',       pct: 84 },
};

// seconds -> "H:MM:SS" timecode into the VOD (e.g. 1:24:30)
function fmtClock(s){
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  return `${h}:${String(m).padStart(2,'0')}:${String(ss).padStart(2,'0')}`;
}
// seconds -> "M:SS" clip length (e.g. 0:42)
function fmtDur(s){
  s = Math.max(0, Math.round(s || 0));
  const m = Math.floor(s / 60), ss = s % 60;
  return `${m}:${String(ss).padStart(2,'0')}`;
}

/* ---------- atoms ---------- */
function EyeMark({ size=34, glow=true, style }){
  return (
    <img src="assets/eye-logo.png" alt="" className="eye"
      style={{ width:size, height:'auto', objectFit:'contain',
        filter: glow? 'drop-shadow(0 0 16px rgba(255,255,255,.35))':'none', ...style }} />
  );
}

function Wordmark({ size=18, dot=true }){
  return (
    <div style={{ display:'flex', alignItems:'center', gap:11 }}>
      {dot && <EyeMark size={size*1.7} glow={true} style={{ marginRight:1 }} />}
      <span className="disp" style={{ fontSize:size, fontStretch:'100%', letterSpacing:'.02em' }}>
        CLIPMAKER<span style={{ color:'var(--acc)' }}>.AI</span>
      </span>
    </div>
  );
}

// thin concentric targeting reticle (decorative)
function Reticle({ size=260, style, spin=true }){
  const s = size;
  return (
    <svg width={s} height={s} viewBox="0 0 200 200" style={{ position:'absolute', pointerEvents:'none', ...style }}>
      <g className={spin? 'spin':''} style={{ transformOrigin:'100px 100px' }}>
        <circle cx="100" cy="100" r="96" fill="none" stroke="rgba(255,255,255,.14)" strokeWidth=".5" />
        <circle cx="100" cy="100" r="70" fill="none" stroke="rgba(255,255,255,.10)" strokeWidth=".5" strokeDasharray="2 4" />
        {[...Array(12)].map((_,i)=>(
          <line key={i} x1="100" y1="4" x2="100" y2="12"
            stroke="rgba(255,255,255,.2)" strokeWidth=".6"
            transform={`rotate(${i*30} 100 100)`} />
        ))}
      </g>
      <circle cx="100" cy="100" r="46" fill="none" stroke="rgba(255,255,255,.16)" strokeWidth=".5" />
      <line x1="100" y1="46" x2="100" y2="62" stroke="rgba(255,255,255,.25)" strokeWidth=".6" />
      <line x1="100" y1="138" x2="100" y2="154" stroke="rgba(255,255,255,.25)" strokeWidth=".6" />
      <line x1="46" y1="100" x2="62" y2="100" stroke="rgba(255,255,255,.25)" strokeWidth=".6" />
      <line x1="138" y1="100" x2="154" y2="100" stroke="rgba(255,255,255,.25)" strokeWidth=".6" />
    </svg>
  );
}

// corner registration marks for a framed area
function Corners({ inset=10, len=14, color='var(--line2)' }){
  const c = { position:'absolute', width:len, height:len, borderColor:color, pointerEvents:'none' };
  return (<>
    <span style={{...c, top:inset, left:inset, borderTop:'1px solid', borderLeft:'1px solid'}} />
    <span style={{...c, top:inset, right:inset, borderTop:'1px solid', borderRight:'1px solid'}} />
    <span style={{...c, bottom:inset, left:inset, borderBottom:'1px solid', borderLeft:'1px solid'}} />
    <span style={{...c, bottom:inset, right:inset, borderBottom:'1px solid', borderRight:'1px solid'}} />
  </>);
}

// score readout ring
function ScoreRing({ value=80, size=46 }){
  const r = 20, c = 2*Math.PI*r, off = c*(1-value/100);
  const col = value>=90? 'var(--acc)' : value>=80? '#dfe0e2' : 'var(--muted)';
  return (
    <svg width={size} height={size} viewBox="0 0 48 48">
      <circle cx="24" cy="24" r={r} fill="none" stroke="rgba(255,255,255,.1)" strokeWidth="2" />
      <circle cx="24" cy="24" r={r} fill="none" stroke={col} strokeWidth="2"
        strokeDasharray={c} strokeDashoffset={off} strokeLinecap="round"
        transform="rotate(-90 24 24)" />
      <text x="24" y="27" textAnchor="middle" fontFamily="var(--mono)" fontSize="12" fill={col}>{value}</text>
    </svg>
  );
}

// clip preview — the real rendered vertical clip frame, with the same reticle/timecode
// overlays. The placeholder reticle shows only while the clip is still rendering
// (no file yet); once file_path exists, the real 9:16 <video> fills the frame.
function ClipThumb({ clip, h=300, vertical=true }){
  const ready = !!clip.file_path;
  const ovl = { pointerEvents:'none' };  // overlays must not eat clicks meant for the <video>
  return (
    <div style={{ position:'relative', width:'100%', height:h, overflow:'hidden',
      background:'linear-gradient(160deg,#101014,#070708 70%)', border:'1px solid var(--line)' }}>
      {ready ? (
        <video src={`/clips/${clip.id}.mp4`} controls preload="none" playsInline
          style={{ position:'absolute', inset:0, width:'100%', height:'100%',
            objectFit:'cover', background:'#000', display:'block' }} />
      ) : (
        <Reticle size={h*0.55} spin={false}
          style={{ left:'50%', top:'46%', transform:'translate(-50%,-50%)', opacity:.5 }} />
      )}
      <div style={{ position:'absolute', inset:0, pointerEvents:'none',
        background:'repeating-linear-gradient(180deg,transparent 0 2px,rgba(255,255,255,.015) 2px 3px)' }} />
      <Corners inset={8} len={11} />
      <div className="mono" style={{ ...ovl, position:'absolute', top:10, left:12, fontSize:10, color:'var(--muted)', letterSpacing:'.1em' }}>
        ◉ REC · {clip.t}
      </div>
      <div className="mono" style={{ ...ovl, position:'absolute', top:10, right:12, fontSize:10, color:'var(--faint)' }}>
        {vertical?'9:16':'16:9'}
      </div>
      <div className="mono" style={{ ...ovl, position:'absolute', bottom:10, right:12, fontSize:11,
        color:'var(--text)', background:'rgba(0,0,0,.6)', padding:'3px 7px', border:'1px solid var(--line2)' }}>
        {clip.dur}
      </div>
    </div>
  );
}

Object.assign(window, { API, STAGE, fmtClock, fmtDur, EyeMark, Wordmark, Reticle, Corners, ScoreRing, ClipThumb });
