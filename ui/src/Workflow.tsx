import { useState } from 'react';

const nodes = [
  ['validate_alert','Enter the workflow','The runner validates the alert and snapshot bounds before entering the graph. This node records entry and routes to triage.'],
  ['triage','Choose a first step','The model requests one tool or chooses to finish. Failed model calls and exhausted budgets route to finalization.'],
  ['guard_action','Route the decision','Validate tool and snapshot scope. A query outside the alert window pauses for approval before collection. Finish decisions route to finalization.'],
  ['human_approval','Review expanded scope','Approve the exact saved query or decline and finalize. SQLite checkpoints preserve evidence and budgets across a server restart.'],
  ['collect_evidence','Query saved evidence','The application validates arguments and scope, enforces limits, and calls one of five read-only tools. Duplicates use cached results.'],
  ['assess','Decide whether to continue','The model sees collected observations, cited hypothesis summaries and tool feedback. Two consecutive steps without progress stop the loop; otherwise it can choose another tool.'],
  ['finalize','Build and validate the report','The model writes a structured report. The application validates its schema and citations. If that fails, it returns an operational partial outcome.'],
] as const;

export function Workflow({path=[],workflow,reason,runs=[],onSelectRun}:{path?:string[];workflow?:string;reason?:string;runs?:{run_id:string;workflow?:string;state:string}[];onSelectRun?:(id:string)=>void}) {
  const [selected,setSelected]=useState('triage');
  const detail=nodes.find(node=>node[0]===selected)!;
  return <section className="workflow-view">
    <p className="eyebrow">HOW THE INVESTIGATOR WORKS</p><h1>One bounded investigation loop.</h1>
    <p className="lede">LangGraph routes the adaptive workflow. The application owns tool permissions, evidence records and resource limits.</p>
    <div className="notice"><b>Fixed vs. adaptive.</b> Fixed collection runs a predefined query sequence and then finalizes. Adaptive collection uses the graph below to choose each next step.</div>
    <section className="card graph-card" aria-label="Adaptive workflow graph">
      <div className="section-label">SELECT A STEP TO EXPLORE</div>
      <ol className="graph-nodes">{nodes.map(([id,title],i)=><li key={id}><button aria-pressed={selected===id} onClick={()=>setSelected(id)}><small>{String(i+1).padStart(2,'0')} / {id}</small><strong>{title}</strong></button></li>)}</ol>
      <p className="graph-routing">Start → Enter → Choose → Route → Collect → Assess ↺ Route<br/>Expanded window → Pause → Approve → Collect / Decline → Finalize<br/>Finish decisions or exhausted limits → Finalize → End</p>
      <div className="node-detail" aria-live="polite"><h2>{detail[1]}</h2><p>{detail[2]}</p></div>
    </section>
    <section className="card graph-card"><div className="section-label">ACTUAL SELECTED RUN</div><div className="field"><label htmlFor="graph-run">Saved run</label><select id="graph-run" defaultValue="" onChange={e=>{if(e.target.value)onSelectRun?.(e.target.value);}}><option value="">Choose an existing run</option>{runs.map(run=><option key={run.run_id} value={run.run_id}>{run.workflow || 'Run'} · {run.run_id.slice(0,8)} · {run.state}</option>)}</select></div>
      {path.length?<><h2>{workflow==='fixed'?'Fixed collection path':'Recorded graph path'}</h2><p className="hint">{workflow==='fixed'?'Fixed collection runs outside LangGraph; only its finalization is recorded here.':'Repeated steps show the loop actually taken, rather than a simulated animation.'}</p><ol className="execution-path">{path.map((name,i)=><li key={i}>{name.replaceAll('_',' ')}</li>)}</ol><p>Stop reason: <strong>{reason?.replaceAll('_',' ') || 'Unavailable'}</strong></p></>:<p>Open an investigation from Recent runs, or start one, to see its recorded path here.</p>}
    </section>
    <section className="card graph-card"><h2>What this demonstrates</h2><p>Five bounded read-only tools (logs, metrics, changes, runbooks and traces), cited hypothesis updates, event-time timelines, human claim review, six investigation steps plus a human approval node, conditional routing, a repeated evidence loop, explicit stopping rules, and validated final output.</p><p className="hint">Interactive adaptive investigations save versioned evidence, decisions, activity and budgets in SQLite. A saved approval can resume after restart. Unknown external-call outcomes retain reservations and require a new investigation. Historical archives and standalone evaluation runs are not resumable checkpoints.</p></section>
  </section>;
}
