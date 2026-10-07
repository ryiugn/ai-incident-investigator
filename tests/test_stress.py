import pytest
from investigator.snapshot import Snapshot
from investigator.runner import run_investigation
from investigator.provider import ScriptedProvider


def test_stress_fixtures_are_distinct_handcrafted_public_observations():
    from investigator.stress import stress_cases
    cases=stress_cases()
    assert set(cases)=={'stress-simultaneous','stress-nearby-change','stress-intermittent','stress-incomplete','stress-healthy-lookalike'}
    assert len({c['telemetry_snapshot']['snapshot_id'] for c in cases.values()})==5
    for case in cases.values():
        Snapshot.model_validate(case['telemetry_snapshot'])
        assert case['source']=='handcrafted stress fixture'
        assert 'true_cause' not in str(case) and 'capture_id' not in str(case)
    assert {r['event_code'] for r in cases['stress-simultaneous']['telemetry_snapshot']['logs']} >= {'dependency_timeout','pool_timeout'}
    assert cases['stress-nearby-change']['telemetry_snapshot']['changes']
    assert {r['event_code'] for r in cases['stress-intermittent']['telemetry_snapshot']['logs']} >= {'request_ok','dependency_timeout'}
    assert cases['stress-incomplete']['telemetry_snapshot']['complete'] is False
    healthy=cases['stress-healthy-lookalike']['telemetry_snapshot']
    assert all(r['event_code']!='dependency_timeout' for r in healthy['logs'])
    assert any(r['metric']=='dependency_duration_p95' and r['value']>400 for r in healthy['metrics'])

@pytest.mark.parametrize('name',['stress-simultaneous','stress-nearby-change','stress-intermittent','stress-incomplete','stress-healthy-lookalike'])
@pytest.mark.parametrize('workflow',['fixed','adaptive'])
async def test_stress_runs_are_bounded_software_demonstrations(name,workflow):
    from investigator.stress import stress_cases
    result=await run_investigation(stress_cases()[name],ScriptedProvider(),workflow=workflow)
    assert result['usage']['tool_dispatches']<=8
    assert result['usage']['estimated_cost_usd']==0
    assert 'Scripted demonstration' in result['report']['uncertainty']
    if name=='stress-healthy-lookalike':
        assert result['report']['status']=='insufficient_evidence'


def test_stress_case_selector_explicit_source(tmp_path):
    from fastapi.testclient import TestClient
    from investigator.api import create_app
    with TestClient(create_app(archive=tmp_path,public=tmp_path/'public')) as c:
        cases=c.get('/api/cases').json()
        stress=[x for x in cases if x['case_id'].startswith('stress-')]
        assert len(stress)==5
        assert all(x['source']=='handcrafted stress fixture' for x in stress)
