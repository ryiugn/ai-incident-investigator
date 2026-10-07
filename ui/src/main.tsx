import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { Workflow } from './Workflow';
import {ReviewPanel,ReviewStatus,RunComparison} from './Review';
import {InvestigationContext} from './Context';
import type {Hypothesis,Timeline} from './Context';

type Case = {case_id:string; symptom:string; source:string; window:{start:string;end:string}};
type Evidence = {evidence_id:string;content_hash:string;source_kind:string;source_record_ids:string[];snapshot_id:string;payload:Record<string,unknown>;coverage:Record<string,unknown>};
type Claim = {text:string;evidence_ids:string[];limitations?:string};
type Report = {status:string;likely_cause:Claim|null;observed_symptoms:Claim[];diagnostic_level:string;uncertainty:string;missing_evidence:string[];next_steps:{action:string;purpose:string;evidence_ids:string[]}[];alternatives:{description:string;unresolved_reason:string;supporting_ids:string[];contradicting_ids:string[]}[]};
type Approval = {token:{approval_id:string;checkpoint_id:string;revision:number};query:{tool:string;arguments:Record<string,unknown>};summary:string;reason:string;requested_window:{start:string;end:string};original_window:{start:string;end:string};allowed_scope:{start:string;end:string}};
type Run = {run_id:string;state:string;workflow?:string;resumable?:boolean;recovery_message?:string;pending_approval?:Approval|null;result?:{hypotheses?:Hypothesis[];hypothesis_history?:unknown[];timeline?:Timeline;nodes?:string[];report:Report|null;evidence:Record<string,Evidence>;events:{tool?:string;status?:string;summary?:string;duplicate?:boolean;error?:string}[];usage:{tool_dispatches:number;model_requests:number;elapsed_ms:number;estimated_cost_usd:number};termination_reason:string}};
type Fraction = {numerator:number;denominator:number;value:number|null};
type Arm = {scheduled_runs:number;valid_completion:Fraction;supported_diagnosis:Fraction;appropriate_abstention:Fraction;claim_support:Fraction;latency_ms:{median:number;p90:number};total_cost_usd:number;total_input_tokens:number;total_output_tokens:number};
type Comparison = {batch_id:string;provider:string;split:string;findings_status:string;arms:Record<string,Arm>};

async function api<T>(path:string, body?:unknown):Promise<T> {
  const r=await fetch('/api'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);
  if(!r.ok) throw new Error((await r.json()).detail || 'Request failed');
  return r.json();
}

function App(){
  const [tab,setTab]=useState('investigation'),[cases,setCases]=useState<Case[]>([]),[caseId,setCaseId]=useState('demo');
  const [workflow,setWorkflow]=useState('adaptive'),[job,setJob]=useState<Run|null>(null),[history,setHistory]=useState<Run[]>([]);
  const [evidence,setEvidence]=useState<Evidence|null>(null),[comparisons,setComparisons]=useState<Comparison[]>([]),[error,setError]=useState(''),[starting,setStarting]=useState(false);
  const [config,setConfig]=useState({provider:'scripted-v1',paid:false});
  const [submitting,setSubmitting]=useState(false);
  const [showContext,setShowContext]=useState(false),[reviewRevision,setReviewRevision]=useState(0);
  const [showReview,setShowReview]=useState(false),[showCompare,setShowCompare]=useState(false);
  useEffect(()=>{setShowReview(false)},[job?.run_id]);
  const inspectorHeading=useRef<HTMLHeadingElement>(null), citationOrigin=useRef<HTMLButtonElement|null>(null);
  useEffect(()=>{
    if(!evidence || tab!=='investigation')return;
    const heading=inspectorHeading.current;
    heading?.closest('.inspector')?.scrollTo({top:0});
    heading?.focus({preventScroll:true});
    heading?.scrollIntoView({block:'start',behavior:'instant'});
  },[evidence]);
  function returnToCitation(){
    const origin=citationOrigin.current;
    if(!origin?.isConnected)return;
    origin.focus({preventScroll:true});
    origin.scrollIntoView({block:'center',behavior:'instant'});
  }
  const refresh=()=>api<Run[]>('/runs').then(setHistory).catch(e=>setError(e.message));
  useEffect(()=>{api<Case[]>('/cases').then(setCases).catch(e=>setError(e.message));api<typeof config>('/config').then(setConfig); refresh();},[]);
  useEffect(()=>{if(tab==='benchmark')api<Comparison[]>('/comparisons').then(setComparisons).catch(e=>setError(e.message));},[tab]);
  useEffect(()=>{
    if(!job || !['queued','running'].includes(job.state))return;
    const timer=setInterval(()=>api<Run>('/runs/'+job.run_id).then(r=>{setJob(r);if(r.state!=='running'&&r.state!=='queued')refresh();}).catch(e=>setError(e.message)),400);
    return ()=>clearInterval(timer);
  },[job?.run_id,job?.state]);
  async function start(){setError('');setStarting(true);setEvidence(null);try{const r=await api<{run_id:string}>('/runs',{case_id:caseId,workflow});setJob({run_id:r.run_id,state:'queued'});}catch(e){setError((e as Error).message);}finally{setStarting(false);}}
  async function continueRun(decision?:'approve'|'decline'){
    if(!job)return;
    setSubmitting(true);setError('');
    try{
      const body=decision?{...job.pending_approval!.token,decision}:{};
      setJob(await api<Run>(`/runs/${job.run_id}/${decision?'approval':'resume'}`,body));
      refresh();
    }catch(e){setError((e as Error).message);setJob(await api<Run>('/runs/'+job.run_id));}
    finally{setSubmitting(false);}
  }
  async function inspect(id:string, origin?:HTMLButtonElement){if(!job)return;citationOrigin.current=origin || null;try{setEvidence(await api<Evidence>(`/runs/${job.run_id}/evidence/${id}`));}catch(e){setError((e as Error).message);}}
  const refs=(ids:string[])=> <span className="refs">{ids.map((id,i)=><button key={id} aria-label={`Inspect evidence ${i+1}`} title={id} aria-controls="evidence-inspector" onClick={event=>inspect(id,event.currentTarget)}>[{i+1}]</button>)}</span>;
  const active=starting || !!job&&['queued','running'].includes(job.state),report=job?.result?.report;
  const selected=cases.find(c=>c.case_id===caseId);
  return <div className="shell">
    <aside><div className="brand"><span className="brand-icon">⌕</span><div>Incident<br/><strong>Investigator</strong></div></div><div className="workspace">LOCAL WORKSPACE <span>●</span></div>
      <nav aria-label="Main navigation"><button aria-label="Investigation" className={tab==='investigation'?'selected':''} onClick={()=>setTab('investigation')}><span aria-hidden="true">◉</span> <span>Investigation</span></button><button aria-label="Benchmark" className={tab==='benchmark'?'selected':''} onClick={()=>setTab('benchmark')}><span aria-hidden="true">▥</span> <span>Benchmark</span></button><button aria-label="Graph walkthrough" className={tab==='workflow'?'selected':''} onClick={()=>setTab('workflow')}><span aria-hidden="true">↳</span><span>Workflow</span></button></nav>
      <div className="history"><h3 id="recent-runs-title">RECENT RUNS</h3><div className="history-list" role="region" aria-labelledby="recent-runs-title" tabIndex={0}>{history.map(r=><button key={r.run_id} onClick={()=>{api<Run>('/runs/'+r.run_id).then(setJob).catch(e=>setError(e.message));setEvidence(null);setTab('investigation');}}><span>{r.workflow || 'Run'} · {r.run_id.slice(0,6)}</span><small>{r.state}</small></button>)}{!history.length&&<p>Your investigations will appear here.</p>}</div></div>
      <div className="sidebar-footer"><span className="dot"/> {config.paid?config.provider:'Scripted provider'}<br/><small>{config.paid?'Approved ceiling enforced':'No API spend'} · read-only</small></div>
    </aside>
    <main><header><span>WORKSPACE / {tab.toUpperCase()}</span><span className="pill">LOCAL DEVELOPMENT</span></header>
      {error&&<div role="alert" className="error">{error}<button onClick={()=>setError('')}>Dismiss</button></div>}
      {tab==='investigation'?<>
        <div className="title-row"><div><p className="eyebrow">FROM SYMPTOM TO SOURCE</p><h1>Investigate with evidence.</h1><p className="lede">Trace a failure. Inspect the observations. Know what remains uncertain.</p></div><span className="version">REPLAY / V1</span></div>
        <section className="setup"><div className="field grow"><label htmlFor="case">Replay case</label><select id="case" value={caseId} onChange={e=>setCaseId(e.target.value)}>{cases.map(c=><option key={c.case_id} value={c.case_id}>{c.case_id==='demo'?'Dependency timeout · demo fixture':c.case_id==='demo-missing'?'Missing evidence · demo fixture':`${c.case_id.slice(0,8)} · ${c.symptom}`}</option>)}</select></div><div className="field"><label htmlFor="workflow">Workflow</label><select id="workflow" value={workflow} onChange={e=>setWorkflow(e.target.value)}><option value="adaptive">Adaptive investigation</option><option value="fixed">Fixed collection</option></select></div><button className="primary" disabled={active} onClick={start}>{active?'Investigating…':'Start investigation'} <span>↗</span></button></section>
        <div className="case-meta"><span>{selected?.source || 'Loading cases…'}</span><span>orders</span><span>{selected?new Date(selected.window.start).toISOString().replace('T',' ').slice(0,19)+' UTC':''}</span><button onClick={()=>api<Case[]>('/cases').then(setCases).catch(e=>setError(e.message))}>Refresh captures</button></div>
        <div className="notice">{config.paid?<><b>Hosted model enabled.</b> Review evidence support separately from citation integrity. Usage is charged against the configured local ceiling.</>:<><b>Scripted demonstration.</b> Reports exercise the application; they do not measure LLM diagnostic ability.</>}</div>
        {!job&&<section className="empty"><div className="empty-mark">⌕</div><h2>A clear trail from alert to evidence</h2><p>Choose a replay and start an investigation. Every cited observation opens its immutable source.</p><div className="steps"><span>01 · Collect</span><span>02 · Assess</span><span>03 · Inspect</span></div></section>}
        {job&&<><div className="run-top"><span className="pill">{job.state.toUpperCase()}</span><code>{job.run_id.slice(0,12)}</code>{job.result&&<span>{job.result.usage.tool_dispatches} tool attempts · {job.result.usage.model_requests} model requests · {job.result.usage.elapsed_ms} ms</span>}</div>
        {active&&<div className="empty" role="status"><h2>Collecting and checking evidence…</h2><p>The run has bounded tools, requests and elapsed time.</p></div>}
        {job.pending_approval&&<section className="card approval" aria-labelledby="approval-title"><div className="section-label">HUMAN APPROVAL REQUIRED</div><h2 id="approval-title">Review expanded evidence query</h2><p>{job.pending_approval.reason}</p><p>{job.pending_approval.summary}</p><dl><dt>Proposed read-only query</dt><dd>{job.pending_approval.query.tool.replaceAll('_',' ')}</dd><dt>Requested time range</dt><dd>{job.pending_approval.requested_window.start} → {job.pending_approval.requested_window.end}</dd><dt>Original alert window</dt><dd>{job.pending_approval.original_window.start} → {job.pending_approval.original_window.end}</dd><dt>Frozen snapshot horizon</dt><dd>{job.pending_approval.allowed_scope.start} → {job.pending_approval.allowed_scope.end}</dd></dl><details><summary>Exact query arguments</summary><pre>{JSON.stringify(job.pending_approval.query.arguments,null,2)}</pre></details><p className="hint">Approval applies only to this saved query. Scope and resource limits still apply. Waiting does not consume active execution time.</p><div className="approval-actions"><button className="primary" disabled={submitting} onClick={()=>continueRun('approve')}>{submitting?'Continuing…':'Approve exact query'}</button><button disabled={submitting} onClick={()=>continueRun('decline')}>Decline and finalize</button></div></section>}
        {['interrupted','error'].includes(job.state)&&<div role="alert" className="notice"><p>{job.recovery_message || 'This run has no resumable checkpoint. Start a new investigation to continue.'}</p>{job.resumable&&<button className="primary" disabled={submitting} onClick={()=>continueRun()}>{submitting?'Resuming…':'Resume investigation'}</button>}</div>}
        {report&&<><div className="approval-actions"><button onClick={()=>setShowReview(!showReview)}>Review report</button><button onClick={()=>setShowCompare(!showCompare)}>Compare runs</button><button onClick={()=>setShowContext(!showContext)}>Investigation context</button><ReviewStatus key={job.run_id} runId={job.run_id} revision={reviewRevision}/></div>{showReview&&<ReviewPanel key={job.run_id} onSaved={()=>setReviewRevision(v=>v+1)} runId={job.run_id} report={report} evidence={job.result?.evidence||{}}/>}{showCompare&&<RunComparison runs={history}/>} {showContext&&<InvestigationContext hypotheses={job.result?.hypotheses} history={job.result?.hypothesis_history} timeline={job.result?.timeline} onEvidence={inspect}/>}<div className="investigation-grid"><div><section className="report card"><div className="section-label">INVESTIGATION REPORT <span>{report.diagnostic_level.replaceAll('_',' ')}</span></div><h2>{report.status==='diagnosis'?'Observed failure condition':report.status==='insufficient_evidence'?'Insufficient evidence':'Partial investigation'}</h2>
          {report.likely_cause&&<p className="diagnosis">{report.likely_cause.text} {refs(report.likely_cause.evidence_ids)}</p>}
          <p className="uncertainty">{report.uncertainty}</p>
          {report.observed_symptoms.length>0&&<><h3>Observed symptoms</h3>{report.observed_symptoms.map((c,i)=><p key={i}>{c.text} {refs(c.evidence_ids)}</p>)}</>}
          <h3>Missing evidence</h3><ul>{report.missing_evidence.map(s=><li key={s}>{s}</li>)}</ul>
          {report.alternatives.length>0&&<><h3>Unresolved alternatives</h3>{report.alternatives.map((a,i)=><p key={i}>{a.description} {a.unresolved_reason} {refs([...a.supporting_ids,...a.contradicting_ids])}</p>)}</>}
          <h3>Suggested next checks</h3>{report.next_steps.map((s,i)=><div className="next-step" key={i}><span>{String(i+1).padStart(2,'0')}</span><div><strong>{s.action}</strong><p>{s.purpose} {refs(s.evidence_ids)}</p></div></div>)}
          <footer>Suggestions only. No remediation is executed. · {job.result?.termination_reason}</footer>
        </section><section className="card trail"><div className="section-label">OBSERVABLE ACTIVITY</div>{job.result?.events.map((e,i)=><div key={i} className="event"><span className="event-dot"/><div><strong>{e.tool?.replaceAll('_',' ') || 'Decision'}</strong><p>{e.summary || e.error || (e.duplicate?'Cached duplicate; no new dispatch':e.status)}</p></div></div>)}</section></div>
        <section id="evidence-inspector" aria-labelledby="evidence-title" className="card inspector"><div className="section-label">SOURCE RECORD</div><h2 id="evidence-title" ref={inspectorHeading} tabIndex={-1}>Evidence inspector</h2>{evidence&&citationOrigin.current?.isConnected&&<button className="back-to-citation" onClick={returnToCitation}>← Back to citation</button>}{evidence?<><span className="pill">{evidence.source_kind}</span><dl><dt>Evidence ID</dt><dd>{evidence.evidence_id}</dd><dt>Snapshot</dt><dd>{evidence.snapshot_id}</dd><dt>Content hash</dt><dd>{evidence.content_hash}</dd></dl><h3>Source payload</h3><pre>{JSON.stringify(evidence.payload,null,2)}</pre><h3>Coverage</h3><pre>{JSON.stringify(evidence.coverage,null,2)}</pre><p className="hint">Citation integrity is checked. Whether this source supports the claim requires separate review.</p></>:<><p className="hint">Select a citation in the report or an evidence item below.</p><div className="evidence-list">{Object.values(job.result?.evidence || {}).map((e,i)=><button key={e.evidence_id} onClick={()=>inspect(e.evidence_id)}>{String(i+1).padStart(2,'0')} · {e.source_kind}<span>↗</span></button>)}</div></>}</section></div></>}</>}
      </>:tab==='workflow'?<Workflow runs={history} onSelectRun={id=>api<Run>('/runs/'+id).then(setJob).catch(e=>setError(e.message))} path={job?.result?.nodes} workflow={job?.workflow} reason={job?.result?.termination_reason}/>:<><p className="eyebrow">THE CENTRAL EXPERIMENT</p><h1>Fixed vs. adaptive</h1><p className="lede">Does adaptive investigation yield more useful, supported diagnoses?</p><div className="notice"><b>Real-model findings pending</b><p>Scripted runs verify orchestration. Diagnostic correctness and claim support require human review. No winner is assumed.</p></div>
        {!comparisons.length&&<section className="empty"><h2>No archived comparison yet</h2><p>Run the development experiment to populate this view.</p></section>}
        {comparisons.map(c=><section className="card benchmark" key={c.batch_id}><div className="section-label">{c.split.toUpperCase()} · {c.provider.toUpperCase()} <span>{c.batch_id.slice(0,8)}</span></div><h2>Archived comparison</h2><p className="hint">{c.findings_status}</p><table><thead><tr><th>Measure</th><th>Fixed</th><th>Adaptive</th></tr></thead><tbody>{(['scheduled_runs','valid_completion','supported_diagnosis','appropriate_abstention','claim_support'] as const).map(key=><tr key={key}><td>{key.replaceAll('_',' ')}</td>{['fixed','adaptive'].map(arm=>{const value=c.arms[arm][key];return <td key={arm}>{typeof value==='number'?value:value.value===null?<span className="pending">Pending review</span>:`${value.numerator} / ${value.denominator}`}</td>})}</tr>)}<tr><td>Median / p90 latency</td>{['fixed','adaptive'].map(arm=><td key={arm}>{c.arms[arm].latency_ms.median} / {c.arms[arm].latency_ms.p90} ms</td>)}</tr><tr><td>Provider cost</td>{['fixed','adaptive'].map(arm=><td key={arm}>${c.arms[arm].total_cost_usd.toFixed(4)}</td>)}</tr></tbody></table><p className="hint">All scheduled failures remain in denominators. Related variants share capture groups. Scripted latency excludes container startup and does not estimate hosted-model latency.</p></section>)}</>}
      <footer className="page-footer">AI Incident Investigator <span>Evidence first. Conclusions with limits.</span></footer>
    </main>
  </div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
