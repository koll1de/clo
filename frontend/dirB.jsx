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
  // a finished job whose clips we're browsing in the viewer modal (all statuses), and its clips
  const [openJob, setOpenJob] = useState(null);
  const [jobClips, setJobClips] = useState([]);

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

  // optimistically pull a card from the grid (the 3s poll re-syncs from the server)
  const drop = (id) => { acted.current.add(id); setClips(x => x.filter(y => y.id !== id)); };

  // SKIP -> reject (discard the clip)
  const skip = async (c) => { drop(c.id); try { await API.reject(c.id); } catch (e) {} refresh(); };

  // EXPORT -> download the finished .mp4 to disk, then mark it approved (leaves the queue)
  const exportClip = async (c) => {
    if (!c.file_path) { alert('This clip is still rendering — try again in a moment.'); return; }
    const a = document.createElement('a');
    a.href = API.clipUrl(c.id); a.download = `clip-${c.id}.mp4`;
    document.body.appendChild(a); a.click(); a.remove();
    drop(c.id); try { await API.approve(c.id); } catch (e) {} refresh();
  };

  // POST -> publish straight to the enabled platform(s) (YouTube Shorts / TikTok)
  const post = async (c) => {
    if (!c.file_path) { alert('This clip is still rendering — try again in a moment.'); return; }
    try {
      const r = await API.publish(c.id);
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        alert("Can't post yet: " + (j.detail || 'no publishing platform is enabled') +
              '\n\nEnable youtube/tiktok in config.yaml and follow SETUP_PUBLISHING.md, then try again.');
        return;  // keep the card so they can retry after configuring a platform
      }
      drop(c.id);
    } catch (e) { alert('Post failed: ' + e); return; }
    refresh();
  };

  // delete a whole run (its clips, work files and the downloaded VOD)
  const delJob = async (job) => {
    const name = (job.source || '').split(/[\\/]/).pop() || job.id;
    if (!window.confirm(`Delete this run and all its clips?\n\n${name}`)) return;
    if (openJob && openJob.id === job.id) setOpenJob(null);
    try { await API.delJob(job.id); } catch (e) {}
    refresh();
  };

  // open the viewer for a run and load ALL its clips (any status) so old jobs are browsable
  const viewJob = async (job) => {
    setOpenJob(job); setJobClips([]);
    try { setJobClips(await API.clips(job.id)); } catch (e) { setJobClips([]); }
  };

  // download a clip's .mp4 without changing its status (for browsing old clips)
  const download = (c) => {
    if (!c.file_path) { alert('This clip has no rendered file.'); return; }
    const a = document.createElement('a');
    a.href = API.clipUrl(c.id); a.download = `clip-${c.id}.mp4`;
    document.body.appendChild(a); a.click(); a.remove();
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
                <div style={{ display:'flex', gap:6, marginTop:13 }}>
                  <button className="btn" style={{ flex:1, padding:'8px 4px', fontSize:9, justifyContent:'center' }}
                    onClick={()=>skip(c)}>SKIP</button>
                  <button className="btn" style={{ flex:1, padding:'8px 4px', fontSize:9, justifyContent:'center' }}
                    onClick={()=>exportClip(c)} title="Download the finished .mp4">⤓ EXPORT</button>
                  <button className="btn pri" style={{ flex:1, padding:'8px 4px', fontSize:9, justifyContent:'center' }}
                    onClick={()=>post(c)} title="Publish to YouTube/TikTok">POST</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* runs — every VOD job, with delete (the UI used to show only the latest) */}
      {jobs.length > 0 && (
        <section style={{ maxWidth:1180, margin:'0 auto', padding:'0 44px 90px', position:'relative', zIndex:3 }}>
          <div style={{ display:'flex', alignItems:'baseline', justifyContent:'space-between', marginBottom:18 }}>
            <h2 className="disp" style={{ fontSize:32 }}>Runs <span style={{ color:'var(--faint)' }}>/ {jobs.length}</span></h2>
            <span className="ovl">CLICK A RUN TO VIEW ITS CLIPS · ✕ TO DELETE</span>
          </div>
          <div className="panel">
            {jobs.slice().sort((a,b)=>(b.created_at||0)-(a.created_at||0)).map((j,idx)=>{
              const name = (j.source || '').split(/[\\/]/).pop() || j.id;
              const st = STAGE[j.status];
              const cls = j.status==='ready' ? 'ok' : st ? 'run' : 'q';
              return (
                <div key={j.id} onClick={()=>viewJob(j)} title="View this run's clips"
                  style={{ display:'flex', alignItems:'center', gap:14, padding:'11px 16px', cursor:'pointer',
                  borderTop: idx===0 ? 'none' : '1px solid var(--line)' }}>
                  <span className={`chip ${cls}`} style={{ minWidth:104, justifyContent:'center' }}>
                    <span className="dot" />{st ? st.label : j.status}
                  </span>
                  <span style={{ flex:1, fontSize:13, fontWeight:600, overflow:'hidden',
                    textOverflow:'ellipsis', whiteSpace:'nowrap' }} title={j.source}>{name}</span>
                  <span className="mono" style={{ fontSize:11, color:'var(--faint)', whiteSpace:'nowrap' }}>
                    {j.duration ? fmtDur(j.duration) : '—'}
                  </span>
                  <span className="mono" style={{ fontSize:10, color:'var(--acc)', letterSpacing:'.12em' }}>VIEW ▸</span>
                  <button className="btn x" title="Delete this run + its clips"
                    onClick={(e)=>{ e.stopPropagation(); delJob(j); }}>✕</button>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* clip viewer — browse ALL clips of any run (any status), watch + download/post */}
      {openJob && (
        <div onClick={()=>setOpenJob(null)} style={{ position:'fixed', inset:0, zIndex:50,
          background:'rgba(4,4,5,.86)', overflowY:'auto', padding:'40px 0' }}>
          <div onClick={e=>e.stopPropagation()} style={{ maxWidth:1180, width:'100%', margin:'0 auto', padding:'0 44px' }}>
            <div style={{ display:'flex', alignItems:'baseline', justifyContent:'space-between', marginBottom:20 }}>
              <h2 className="disp" style={{ fontSize:28 }}>
                {(openJob.source || '').split(/[\\/]/).pop() || openJob.id}
                <span style={{ color:'var(--faint)' }}> / {jobClips.length} clips</span>
              </h2>
              <button className="btn ghost" onClick={()=>setOpenJob(null)}>✕ CLOSE</button>
            </div>
            {jobClips.length === 0 ? (
              <div className="mono" style={{ color:'var(--muted)', padding:'40px 0', textAlign:'center' }}>
                No clips for this run.
              </div>
            ) : (
              <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:16, paddingBottom:40 }}>
                {jobClips.slice().sort((a,b)=>(b.score||0)-(a.score||0)).map(c=>(
                  <div key={c.id} className="panel" style={{ position:'relative' }}>
                    <ClipThumb clip={{ ...c, t: fmtClock(c.start), dur: fmtDur(c.end - c.start) }} h={300} />
                    <div style={{ padding:'12px 13px 14px' }}>
                      <div style={{ display:'flex', justifyContent:'space-between', gap:8, alignItems:'center' }}>
                        <div style={{ fontSize:12.5, fontWeight:600, lineHeight:1.25, textWrap:'pretty' }}>{c.title || '(untitled)'}</div>
                        <span className="chip" style={{ fontSize:8.5, padding:'3px 7px' }}>{c.status}</span>
                      </div>
                      <div style={{ display:'flex', gap:6, marginTop:11 }}>
                        <button className="btn" style={{ flex:1, padding:'8px 4px', fontSize:9, justifyContent:'center' }}
                          onClick={()=>download(c)} title="Download the .mp4">⤓ SAVE</button>
                        <button className="btn pri" style={{ flex:1, padding:'8px 4px', fontSize:9, justifyContent:'center' }}
                          onClick={()=>post(c)} title="Publish to YouTube/TikTok">POST</button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
window.DirB = DirB;
