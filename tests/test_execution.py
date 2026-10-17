from investigator.demo import demo_case
from investigator.provider import ScriptedProvider
from investigator.runner import run_investigation
from investigator.checkpoint import Investigations
from test_checkpointing import paused, service


async def test_fixed_playback_links_queries_to_evidence_without_claiming_graph_nodes():
    result = await run_investigation(demo_case(), ScriptedProvider())
    steps = result.get('execution_steps', [])
    assert len(steps) == 7
    assert steps[0]['node'] == 'fixed_query'
    assert steps[0]['events'][0]['tool'] == 'query_logs'
    assert steps[0]['before']['evidence_ids'] == []
    assert steps[0]['after']['evidence_ids']
    assert set(steps[0]['after']['evidence_ids']) <= set(result['evidence'])
    assert steps[-1]['node'] == 'finalize'
    assert steps[-1]['route'] == 'end'
    assert all(s['status'] == 'completed' for s in steps)
    assert all('prompts' not in s and 'payload' not in s for s in steps)


async def test_standalone_records_actual_routes_and_bounded_model_inputs():
    result = await run_investigation(demo_case(), ScriptedProvider(), workflow='adaptive')
    steps = result.get('execution_steps', [])
    assert steps and steps[0]['route'] == 'triage'
    assert [s['node'] for s in steps] == result['nodes']
    triage = next(s for s in steps if s['node'] == 'triage')
    assert triage['decision']['action'] == 'collect'
    assert triage['model_inputs'][0]['evidence_ids'] == []
    assert steps[-1]['after']['report_status'] == result['report']['status']


async def test_recorded_steps_survive_approval_restart_without_duplicates(tmp_path):
    svc, run_id, before = await paused(tmp_path)
    steps = before['result'].get('execution_steps', [])
    assert steps and steps[-1]['route'] == 'human_approval'
    assert not any(s['node'] == 'human_approval' for s in steps)
    after = await service(tmp_path/'checkpoint.sqlite').drive(
        run_id, approval={**before['pending_approval']['token'], 'decision': 'approve'})
    later = after['result']['execution_steps']
    assert later[:len(steps)] == steps
    assert len([s for s in later if s['node'] == 'human_approval']) == 1
    assert [s['sequence'] for s in later] == list(range(1, len(later)+1))


async def test_old_state_defaults_to_no_reconstructed_steps(tmp_path):
    from investigator import checkpoint_state as data
    svc = Investigations(tmp_path/'old.sqlite', ScriptedProvider())
    state = svc.load(svc.create(demo_case()))
    state.pop('execution_steps', None)
    ctx = data.restore(state, svc.provider, svc.adapter_factory)
    assert getattr(ctx, 'execution_steps', None) == []
    assert data.result(state).get('execution_steps') == []


async def test_budget_stopped_assessment_does_not_claim_a_fresh_decision():
    from investigator.budgets import Limits
    result = await run_investigation(demo_case(), ScriptedProvider(), workflow='adaptive',
                                     limits=Limits(model_requests=2))
    assess = next(s for s in result['execution_steps'] if s['node'] == 'assess')
    assert assess['route'] == 'finalize'
    assert assess.get('decision_origin') == 'retained'
    triage = next(s for s in result['execution_steps'] if s['node'] == 'triage')
    assert triage.get('decision_origin') == 'produced_here'
