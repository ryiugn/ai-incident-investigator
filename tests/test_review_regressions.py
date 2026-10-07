import asyncio
import json
import pytest
from investigator.demo import demo_case
from investigator.provider import ScriptedProvider
from investigator.runner import RunContext
from investigator.budgets import Limits
from investigator.telemetry import Telemetry
from investigator.contracts import Decision, ToolRequest


async def test_prompt_preserves_query_completeness_and_omission_metadata():
    ctx=RunContext(demo_case(),ScriptedProvider(),Limits(),Telemetry)
    await ctx.dispatch(ToolRequest(tool='query_logs',arguments={'service':'orders','window':demo_case()['alert']['window'],'limit':1}))
    payload=ctx.payload(Decision)
    event=payload['tool_events'][0]
    assert event['coverage']['complete'] is True
    assert event['truncated'] is False
    assert event['total_matches']==1
    assert event['arguments']['limit']==1
    assert payload['evidence_selection']['omitted_count']==0


async def test_shutdown_during_active_run_finishes(tmp_path,monkeypatch):
    import investigator.api as api_module
    import httpx
    entered=asyncio.Event()
    async def cancelled_runner(*args,**kwargs):
        entered.set()
        try: await asyncio.sleep(5)
        except asyncio.CancelledError: return {'report':{},'evidence':{}}
    monkeypatch.setattr(api_module,'run_investigation',cancelled_runner)
    app=api_module.create_app(archive=tmp_path)
    async def lifecycle():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
                await client.post('/api/runs',json={'case_id':'demo','workflow':'fixed'})
                await entered.wait()
    await asyncio.wait_for(lifecycle(),.5)
    jobs=list((tmp_path/'jobs').glob('*.json'))
    assert json.loads(jobs[0].read_text())['state']=='interrupted'


def test_review_inventory_includes_alternatives_and_requires_complete_judgments():
    from benchmark.evaluate import claim_inventory, validate_review
    report={'likely_cause':{'text':'Pool leak','evidence_ids':['x']},'observed_symptoms':[],
            'alternatives':[{'description':'Database slow','unresolved_reason':'No timing'}],
            'next_steps':[{'action':'Check DB','purpose':'It is unhealthy'}],
            'uncertainty':'Some telemetry is missing','missing_evidence':['Timing']}
    inventory=claim_inventory(report)
    assert any(unit['text']=='It is unhealthy' for unit in inventory)
    with pytest.raises(ValueError):
        validate_review({'reviewer':'human','claim_units':[]},inventory)


def test_worker_honors_effective_limits():
    import subprocess,sys,os
    message=dict(case=demo_case(),workflow='adaptive',provider='scripted',limits={'model_requests':0},model='claude-haiku-4-5-20251001')
    env={**os.environ,'PYTHONPATH':'src'}
    result=subprocess.run([sys.executable,'-m','investigator.worker'],input=json.dumps(message),text=True,capture_output=True,env=env,check=True)
    run=json.loads(result.stdout)
    assert run['usage']['model_requests']==0
    assert run['limits']['model_requests']==0


def test_summary_separates_operational_outcomes():
    from benchmark.metrics import summarize
    result=summarize([dict(answerability='answerable',valid=True,status='error',review=None,usage={})])
    assert result['outcomes']['operational_fallback']==1
    assert result['useful_outcome']['numerator']==0


def test_snapshot_rejects_unapproved_fields_and_duplicate_source_ids():
    snapshot=demo_case()['telemetry_snapshot']
    snapshot['private_answer']='leaked'
    with pytest.raises(ValueError): Telemetry(snapshot)
    snapshot=demo_case()['telemetry_snapshot']
    snapshot['logs']*=2
    with pytest.raises(ValueError): Telemetry(snapshot)
