// dirB.jsx — Direction B · "THE EYE"
// Cinematic, poster-led. Kirlian aura hero, the eye watches the upload target,
// brutalist NEUE-HORIZON title, filmstrip review. Most dramatic of the three.
// Wired to the live backend: jobs/clips polled from FastAPI, real find/stop/skip/export.
function DirB(){
  const { useState, useEffect, useRef } = React;
  const [jobs, setJobs] = useState([]);
  const [clips, setClips] = useState([]);
  const [online, setOnline] = useState(true);
  const [path, setPath] = useState('');
  // clips we've already skipped/exported this session — kept out of the grid so the
  // 3s poll can't briefly re-add one before the server agrees it's no longer pending.
  const acted = useRef(new Set());

  // Pull the live state: all jobs, plus pending clips across every job, by viral score.
  const refresh = async () => {
    try {
      const js = await API.jobs();
      setJobs(js);
      const withClips = js.filter(j => ['finding_moments','rendering','ready','cancelled','error'].includes(j.status));
      const lists = await Promise.all(withClips.map(j => API.clips(j.id).catch(() => [])));
      const pending = lists.flat()
        .filter(c => c.status === 'pending' && !acted.current.has(c.id))
        .sort((a,b) => b.score - a.score);
      setClips(pending);
    } catch (e) { /* transient — keep last good state */ }
  };

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const ok = await API.health();
      if (!alive) return;
      setOnline(ok);
      refresh();
    };
    tick();
    const id = setInterval(tick, 3000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  // the one actively-processing job drives the SCANNING strip (status -> stage + %)
  const runJob = jobs.find(j => STAGE[j.status]);
  const run = runJob && {
    id: runJob.id,
    file: (runJob.source || '').split(/[\\/]/).pop() || 'untitled.mp4',
    stage: STAGE[runJob.status].label,
    progress: STAGE[runJob.status].pct,
  };

  const find = async () => {
    const src = path.trim();
    if (!src) return;
    const isUrl = /^https?:\/\//i.test(src);
    try { await API.createJob(isUrl ? 'twitch' : 'local', src); } catch (e) {}
    setPath('');
    refresh();
  };

  const stop = async () => {
    if (!run) return;
    try { await API.cancel(run.id); } catch (e) {}
    refresh();
  };

  // SKIP -> reject, EXPORT -> approve. Optimistically drop the card, then sync.
  const act = async (c, action) => {
    acted.current.add(c.id);
    setClips(x => x.filter(y => y.id !== c.id));
    try { await (action === 'approve' ? API.approve(c.id) : API.reject(c.id)); } catch (e) {}
    refresh();
  };

  const vodHrs = (jobs.reduce((s,j) => s + (j.duration || 0), 0) / 3600).toFixed(1);

  return (
    <div className="cm" style={{ width:'100%', minHeight:'100%', background:'var(--bg)' }}>
      <div className="cm-grain" /><div className="cm-scan" /><div className="cm-vig" />

      {/* top bar */}
      <header style={{ display:'flex', alignItems:'center', justifyContent:'space-between',
        padding:'20px 44px', position:'relative', zIndex:5 }}>
        <Wordmark size={16} />
        <div style={{ display:'flex', gap:30 }}>
          <span className="ovl">EST · 2026</span>
          <span className="ovl">OPERATOR // AQWE</span>
          <span className="ovl" style={{ color: online ? 'var(--ok)' : 'var(--bad)' }}>
            ● {online ? 'VISION ONLINE' : 'VISION OFFLINE'}
          </span>
        </div>
      </header>

      {/* HERO */}
      <section style={{ position:'relative', padding:'30px 0 60px', overflow:'hidden' }}>
        {/* aura backdrop */}
        <img src="assets/aura.webp" alt="" style={{ position:'absolute', left:'50%', top:'8%',
          transform:'translateX(-50%)', width:560, opacity:.5, mixBlendMode:'screen', pointerEvents:'none',
          maskImage:'radial-gradient(50% 50% at 50% 45%,#000 30%,transparent 72%)',
          WebkitMaskImage:'radial-gradient(50% 50% at 50% 45%,#000 30%,transparent 72%)' }} />
        <Reticle size={520} style={{ left:'50%', top:'2%', transform:'translateX(-50%)', opacity:.5 }} />

        <div style={{ position:'relative', zIndex:3, textAlign:'center', paddingTop:120 }}>
          <div className="ovl" style={{ letterSpacing:'.5em' }}>AUTONOMOUS CLIP INTELLIGENCE</div>
          <h1 className="disp" style={{ fontSize:96, marginTop:14, fontStretch:'125%' }}>
            It sees<br/>every moment
          </h1>
          <p className="mono" style={{ color:'var(--muted)', fontSize:13, marginTop:18, letterSpacing:'.06em' }}>
            Drop a VOD. The eye scans all {vodHrs} hours and surfaces only what goes viral.
          </p>
        </div>

        {/* upload target */}
        <div style={{ position:'relative', zIndex:3, maxWidth:760, margin:'46px auto 0', padding:'0 44px' }}>
          <div className="panel" style={{ position:'relative', padding:'30px 30px',
            background:'linear-gradient(180deg,rgba(255,255,255,.03),transparent)', borderColor:'var(--line2)' }}>
            <Corners inset={12} len={16} color="var(--line3)" />
            <div className="label" style={{ marginBottom:12, textAlign:'center' }}>◉ ACQUIRE TARGET</div>
            <div style={{ display:'flex', gap:12 }}>
              <input className="inp" value={path} onChange={e=>setPath(e.target.value)}
                placeholder="C:\\Users\\aqwe\\Videos\\vod.mp4 — or paste a Twitch / YouTube URL"
                style={{ flex:1, textAlign:'center' }} />
              <button className="btn pri" onClick={find} style={{ whiteSpace:'nowrap' }}>▶ Find clips</button>
            </div>
            <div style={{ display:'flex', justifyContent:'center', gap:24, marginTop:18 }}>
              {['fully automatic','viral-moment detection','runs on your gpu','auto 9:16 + captions'].map(t=>(
                <span key={t} className="mono" style={{ fontSize:9.5, color:'var(--faint)',
                  letterSpacing:'.14em', textTransform:'uppercase' }}>// {t}</span>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* now scanning strip */}
      {run && (
        <section style={{ maxWidth:1180, margin:'0 auto', padding:'0 44px 40px', position:'relative', zIndex:3 }}>
          <div className="panel" style={{ padding:'20px 26px', display:'flex', alignItems:'center', gap:24,
            background:'linear-gradient(90deg,rgba(255,194,26,.07),transparent 70%)', borderColor:'rgba(255,194,26,.25)' }}>
            <span className="disp pulse" style={{ fontSize:13, color:'var(--acc)', fontStretch:'100%' }}>● SCANNING</span>
            <div style={{ flex:1 }}>
              <div style={{ display:'flex', justifyContent:'space-between', marginBottom:8 }}>
                <span style={{ fontSize:14, fontWeight:600 }}>{run.file}</span>
                <span className="mono" style={{ fontSize:11, color:'var(--acc)', letterSpacing:'.14em', textTransform:'uppercase' }}>{run.stage} · {run.progress}%</span>
              </div>
              <div style={{ height:3, background:'rgba(255,255,255,.08)', position:'relative', overflow:'hidden' }}>
                <div style={{ position:'absolute', inset:0, width:`${run.progress}%`, background:'var(--acc)', boxShadow:'0 0 14px var(--acc)' }} />
              </div>
            </div>
            <button className="btn ghost" onClick={stop}>STOP</button>
          </div>
        </section>
      )}

      {/* harvested clips — filmstrip */}
      <section style={{ maxWidth:1180, margin:'0 auto', padding:'10px 44px 90px', position:'relative', zIndex:3 }}>
        <div style={{ display:'flex', alignItems:'baseline', justifyContent:'space-between', marginBottom:22 }}>
          <h2 className="disp" style={{ fontSize:46 }}>Harvested <span style={{ color:'var(--faint)' }}>/ {clips.length}</span></h2>
          <span className="ovl">SORTED BY VIRAL SCORE · {clips.length} PENDING REVIEW</span>
        </div>
        <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:16 }}>
          {clips.map((c,i)=>(
            <div key={c.id} className="panel" style={{ position:'relative', borderColor: i===0?'var(--line3)':'var(--line)' }}>
              {i===0 && <div className="mono" style={{ position:'absolute', top:-1, left:-1, zIndex:4, fontSize:9,
                background:'var(--acc)', color:'#0a0a0a', padding:'4px 8px', letterSpacing:'.12em', fontWeight:700 }}>TOP PICK</div>}
              <ClipThumb clip={{ ...c, t: fmtClock(c.start), dur: fmtDur(c.end - c.start) }} h={340} />
              <div style={{ padding:'13px 14px 15px' }}>
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', gap:10 }}>
                  <div style={{ fontSize:13, fontWeight:600, lineHeight:1.25, textWrap:'pretty' }}>{c.title || '(untitled)'}</div>
                  <ScoreRing value={Math.round((c.score||0)*100)} size={40} />
                </div>
                <div style={{ display:'flex', gap:8, marginTop:13 }}>
                  <button className="btn" style={{ flex:1, padding:'8px', fontSize:10, justifyContent:'center' }}
                    onClick={()=>act(c,'reject')}>SKIP</button>
                  <button className="btn pri" style={{ flex:1, padding:'8px', fontSize:10, justifyContent:'center' }}
                    onClick={()=>act(c,'approve')}>EXPORT</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
window.DirB = DirB;
