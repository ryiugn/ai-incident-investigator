"""Offline evaluation. Semantic scores come only from explicit human review imports."""
import argparse
import json
import os
import random
import subprocess
import time
import uuid
from pathlib import Path
from .dataset import audit_labels, audit_payload
from .metrics import summarize, paired_bootstrap, primary, abstains
from investigator.contracts import Report
from investigator.review import claim_inventory
from investigator.evidence import digest, validate_citations
from investigator.budgets import Limits


def deterministic_checks(result):
    try:
        Report.model_validate(result['report'])
        supplied={e['evidence_id'] for p in result['prompts'] if p['contract']=='Report' for e in p['payload']['evidence']}
        validate_citations(result['report'],result['evidence'],supplied)
        usage,limits=result['usage'],result['limits']
        return all(usage[k]<=limits[k] for k in ('tool_dispatches','model_requests','input_tokens','output_tokens')) and usage['elapsed_ms']<=limits['seconds']*1000+100
    except (ValueError,KeyError,TypeError):
        return False


def isolated_run(message,image='ai-investigator-runtime:local'):
    paid=message['provider']=='anthropic'
    command=['docker','run','--rm','-i','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
             '--memory','512m','--cpus','1','--network','bridge' if paid else 'none']
    if paid: command+=['-e','ANTHROPIC_API_KEY']
    command+=[image]
    completed=subprocess.run(command,input=json.dumps(message),text=True,capture_output=True,timeout=110,check=True)
    return json.loads(completed.stdout)


def select_cases(labels,config,exploratory=False):
    selected=[label for label in labels if label['split']==config['split']]
    ids=config.get('case_ids')
    if ids is not None:
        if not ids or len(ids)!=len(set(ids)) or not set(ids)<={label['case_id'] for label in selected}:
            raise ValueError('case_ids must contain unique cases from the requested split')
        selected=[label for label in selected if label['case_id'] in ids]
    if exploratory and (config['split']!='development' or config['repeats']!=1 or not 1<=len(selected)<=5):
        raise ValueError('Exploratory pilot requires 1-5 development cases and one repeat')
    return selected


def run_batch(config,root=Path('benchmark'),approved_budget_usd=0,exploratory=False):
    root=Path(root)
    labels=json.loads((root/'private'/'labels.json').read_text())
    audit_labels(labels)
    selected=select_cases(labels,config,exploratory)
    paid=config['provider']=='anthropic'
    effective_limits=Limits.model_validate(config['limits']).model_dump()
    if config['model']!='claude-haiku-4-5-20251001': raise ValueError('unverified model/price configuration')
    if paid and not exploratory:
        from .label_review import verify_audit
        verify_audit(root,config['split'])
    if paid:
        from investigator.provider import validate_endpoint
        validate_endpoint()
    image=subprocess.run(['docker','image','inspect','ai-investigator-runtime:local','--format','{{.Id}}'],capture_output=True,text=True,check=True).stdout.strip()
    if paid and (approved_budget_usd<=0 or not os.environ.get('ANTHROPIC_API_KEY')):
        raise ValueError('Paid evaluation requires explicit approved budget and ANTHROPIC_API_KEY')
    if paid and not exploratory and any(l['review_status']!='audited' for l in selected):
        raise ValueError('Complete the human label audit before real-model evaluation')
    batch_id=uuid.uuid4().hex
    destination=root/'results'/batch_id
    destination.mkdir(parents=True)
    rng=random.Random(config['seed'])
    schedule=[]
    for label in selected:
        for repeat in range(config['repeats']):
            arms=['fixed','adaptive']; rng.shuffle(arms)
            schedule += [(label,repeat,arm) for arm in arms]
    rows=[dict(run_id=uuid.uuid4().hex,case_id=l['case_id'],group=l['generation_group_id'],workflow=arm,
        repeat_index=repeat,answerability=l['answerability'],family=l['family'],fault_scheduled=bool(l['failure_schedule']),
        valid=False,status='error',review=None,usage={},termination_reason='not_started') for l,repeat,arm in schedule]
    # This dedicated local checkout may be owned by a Windows sandbox identity.
    # Trust only this exact directory for this read; do not alter global Git configuration.
    commit=subprocess.run(['git','-c',f'safe.directory={Path.cwd().as_posix()}','rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    manifest=dict(batch_id=batch_id,config=config,label_hash=digest(labels),code_commit=commit,
                  lock_hash=digest(Path('requirements.lock.txt').read_text()),image_id=image,config_hash=digest(config),
                  source_hash=digest({str(p):p.read_text(encoding='utf-8-sig') for p in sorted(Path('src').rglob('*.py'))}),
                  exploratory=exploratory,label_review_status='unreviewed' if exploratory else 'audit required for paid evaluation',
                  effective_limits=effective_limits,paid=paid,approved_budget_usd=approved_budget_usd,
                  reserved_or_spent_usd=0,rows=rows)
    def persist():
        (destination/'manifest.json').write_text(json.dumps(manifest,indent=2))
    persist() # Every scheduled run exists even if the process is interrupted.
    for index,((label,repeat,arm),row) in enumerate(zip(schedule,rows)):
        case=json.loads((root/'public'/f"{label['case_id']}.json").read_text())
        if digest(case['telemetry_snapshot'])!=label['snapshot_hash']: raise ValueError('snapshot changed after freeze')
        # Reserve the full run maximum before starting the subprocess. A killed process keeps it.
        reservation=.055 if paid else 0 # 30k input + 5k output at dated 1/5 USD per MTok.
        if paid and manifest['reserved_or_spent_usd']+reservation>approved_budget_usd:
            row['termination_reason']='batch_budget'; persist(); continue
        manifest['reserved_or_spent_usd']+=reservation
        row['termination_reason']='running'; persist()
        start=time.monotonic()
        try:
            result=isolated_run(dict(case=case,workflow=arm,provider=config['provider'],model=config['model'],limits=effective_limits,
                approved_budget_usd=reservation,failure_schedule=label['failure_schedule']),image=image)
            if result['limits']!=effective_limits: raise ValueError('worker configuration differs from frozen limits')
            for prompt in result['prompts']:
                audit_payload(prompt['payload'],[label['generation_group_id']])
            (destination/f"{row['run_id']}.json").write_text(json.dumps(result,indent=2))
            row.update(valid=deterministic_checks(result),status=result['report']['status'],
                       usage=result['usage'],termination_reason=result['termination_reason'])
            if paid:
                actual=result['usage']['estimated_cost_usd']+sum(r['reserved_cost_usd'] for r in result['usage']['unknown_usage_reservations'])
                manifest['reserved_or_spent_usd']+=actual-reservation
        except Exception as error:
            row.update(termination_reason=type(error).__name__,usage={'elapsed_ms':round((time.monotonic()-start)*1000),
                'unknown_usage_reservations':[{'reserved_cost_usd':reservation}] if paid else []})
        persist()
        print(f'{index+1}/{len(rows)} scheduled runs archived',flush=True)
    export_review(destination)
    write_summary(destination)
    return destination


def export_review(directory):
    directory=Path(directory)
    manifest=json.loads((directory/'manifest.json').read_text())
    shuffled=list(manifest['rows']); random.Random(752).shuffle(shuffled)
    labels={l['case_id']:l for l in json.loads((directory.parents[1]/'private'/'labels.json').read_text())}
    packets,mapping=[],{}
    for row in shuffled:
        path=directory/f"{row['run_id']}.json"
        review_id=uuid.uuid4().hex
        mapping[review_id]=row['run_id']
        result=json.loads(path.read_text()) if path.exists() else {}
        label=labels[row['case_id']]
        rubric={key:label[key] for key in ('answerability','maximum_supported_diagnostic_level','acceptable_diagnoses',
            'required_evidence_predicates','forbidden_claims','expected_abstention','useful_action_classes','label_version')}
        prompts=result.get('prompts',[])
        packets.append(dict(review_id=review_id,report=result.get('report'),evidence=result.get('evidence',{}),
            alert=prompts[0]['payload']['alert'] if prompts else None,case_contract=rubric,
            correctness=None,support=None,forbidden_overclaim=None,abstention=None,next_step_utility=None,
            claim_units=claim_inventory(result.get('report',{})),complete_claim_review=False,
            reviewer=None,notes='',rubric_version='v1'))
    (directory/'review-packets.json').write_text(json.dumps(packets,indent=2))
    (directory/'private-review-map.json').write_text(json.dumps(mapping,indent=2))


def validate_review(review,expected):
    if not review.get('reviewer') or review.get('complete_claim_review') is not True:
        raise ValueError('Identified human reviewer and explicit completeness attestation required')
    if review.get('correctness') not in (0,1,2) or review.get('support') not in (0,1,2): raise ValueError('Scores must be 0, 1 or 2')
    if type(review.get('forbidden_overclaim')) is not bool or type(review.get('abstention')) is not bool: raise ValueError('Explicit boolean judgments required')
    if review.get('next_step_utility') not in (0,1,2): raise ValueError('Next-step utility score required')
    units=review.get('claim_units',[])
    if len(units)!=len(expected) or {u['unit_id']:u['text'] for u in units}!={u['unit_id']:u['text'] for u in expected}:
        raise ValueError('All original report text units must be reviewed')
    claims=[]
    for unit in units:
        no_facts=unit.get('contains_no_factual_claims')
        atomic=unit.get('atomic_claims',[])
        if type(no_facts) is not bool or no_facts==bool(atomic): raise ValueError('Classify every unit as nonfactual or supply atomic claims')
        for claim in atomic:
            if not claim.get('text') or claim.get('label') not in ('supported','unsupported','contradicted','unjudgeable'):
                raise ValueError('Each atomic claim needs text and a support judgment')
            claims.append(claim['label'])
    return claims


def import_reviews(directory,review_path):
    directory=Path(directory)
    manifest=json.loads((directory/'manifest.json').read_text())
    mapping=json.loads((directory/'private-review-map.json').read_text())
    by_id={r['run_id']:r for r in manifest['rows']}
    for review in json.loads(Path(review_path).read_text()):
        run_id=mapping[review['review_id']]
        path=directory/f'{run_id}.json'
        report=json.loads(path.read_text()).get('report',{}) if path.exists() else {}
        review['claims']=validate_review(review,claim_inventory(report))
        by_id[run_id]['review']=review
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2))
    write_summary(directory)


def write_summary(directory):
    manifest=json.loads((directory/'manifest.json').read_text())
    rows=manifest['rows']
    summary=dict(batch_id=manifest['batch_id'],provider=manifest['config']['provider'],split=manifest['config']['split'],
        exploratory=manifest.get('exploratory',False),
        findings_status='Exploratory pilot: labels and reports unreviewed; not benchmark findings' if manifest.get('exploratory') else 'Human review pending' if any(r['valid'] and r['review'] is None for r in rows) else 'Reviewed; interpret within benchmark scope',
        arms={arm:summarize([r for r in rows if r['workflow']==arm]) for arm in ('fixed','adaptive')},
        by_family={family:{arm:summarize([r for r in rows if r['family']==family and r['workflow']==arm]) for arm in ('fixed','adaptive')} for family in sorted({r['family'] for r in rows})},
        paired=paired_bootstrap([dict(group=r['group'],workflow=r['workflow'],score=None if r['valid'] and r['review'] is None else int(primary(r) if r['answerability']=='answerable' else abstains(r))) for r in rows]))
    (directory/'summary.json').write_text(json.dumps(summary,indent=2))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,default=Path('benchmark/configs/development.json'))
    parser.add_argument('--approved-budget-usd',type=float,default=0)
    parser.add_argument('--exploratory',action='store_true',help='Explicitly skip human label audit for at most five development cases; never held-out evaluation')
    parser.add_argument('--import-reviews',type=Path)
    parser.add_argument('--batch',type=Path)
    args=parser.parse_args()
    if args.import_reviews: import_reviews(args.batch,args.import_reviews)
    else: print(run_batch(json.loads(args.config.read_text()),approved_budget_usd=args.approved_budget_usd,exploratory=args.exploratory))


if __name__=='__main__': main()
