"""Public hypothesis and event-time context regressions; all fixtures are offline."""
import importlib.util
import pytest
from investigator.contracts import Decision, ToolRequest
from investigator.runner import RunContext, run_investigation
from investigator.demo import demo_case
from investigator.provider import ScriptedProvider, AnthropicProvider
from investigator.telemetry import Telemetry
from investigator.budgets import Limits, Exhausted
from investigator import checkpoint_state


def hypothesis(**updates):
    return dict(hypothesis_id='shipping-delay', candidate='Shipping dependency delay',
                supporting_ids=[], contradicting_ids=[], status='open',
                uncertainty='Underlying mechanism unproven.', next_check='Inspect dependency timing.', **updates)


def test_old_decisions_default_to_no_hypotheses():
    assert Decision(action='report', summary='Done').model_dump().get('hypotheses') == []


async def test_unsupplied_hypothesis_citations_fail_without_entering_history():
    class Invalid(ScriptedProvider):
        async def respond(self, context, contract, max_tokens, timeout):
            item = hypothesis()
            item['supporting_ids'] = ['ev-not-supplied']
            return dict(action='report', summary='Done', hypotheses=[item]), dict(input_tokens=0,output_tokens=0,cache_tokens=0)
    ctx = RunContext(demo_case(), Invalid(), Limits(), Telemetry)
    with pytest.raises(Exhausted, match='invalid_output'):
        await ctx.model(Decision)
    assert getattr(ctx, 'hypothesis_history', None) == []


async def test_updates_keep_latest_and_history_across_checkpoint_restore():
    case = demo_case()
    provider = ScriptedProvider()
    state = checkpoint_state.initial(case, provider, Limits(), Telemetry, 'test-run', 'demo')
    ctx = checkpoint_state.restore(state, provider, Telemetry)
    decision = await ctx.model(Decision)
    await ctx.dispatch(decision.tool_request)
    await ctx.model(Decision)
    state = checkpoint_state.capture(ctx, state)
    restored = checkpoint_state.restore(state, provider, Telemetry)
    result = checkpoint_state.result(state)
    assert len(result.get('hypothesis_history', [])) == 2
    assert result['hypotheses'][0]['hypothesis_id'] == result['hypothesis_history'][0]['hypotheses'][0]['hypothesis_id']
    assert result['hypotheses'][0]['supporting_ids']
    assert restored.hypotheses == ctx.hypotheses
    assert 'demonstration' in result['hypotheses'][0]['uncertainty'].lower()
    state.pop('hypotheses')
    state.pop('hypothesis_history')
    legacy = checkpoint_state.restore(state, provider, Telemetry)
    assert legacy.hypotheses == [] and legacy.hypothesis_history == []


async def test_timeline_uses_utc_event_time_and_keeps_collection_order_separate():
    assert importlib.util.find_spec('investigator.timeline'), 'Evidence timeline projection is missing'
    from investigator.timeline import build_timeline
    result = dict(alert={'triggered_at':'2026-09-01T18:00:00+08:00', 'symptom':'Errors',
                         'window':{'start':'2026-09-01T09:55:00Z','end':'2026-09-01T10:05:00Z'}},
                  snapshot_window={'start':'2026-09-01T09:50:00Z','end':'2026-09-01T10:05:00Z'}, events=[], evidence={
        'later':dict(source_kind='logs', payload={'timestamp':'2026-09-01T18:02:00+08:00','message':'Failure'}),
        'earlier':dict(source_kind='changes', payload={'timestamp':'2026-09-01T09:53:00Z','revision':'r1'}),
        'series':dict(source_kind='metrics', payload={'metric':'error_count','unit':'count','samples':[
            {'start':'2026-09-01T10:00:00Z','end':'2026-09-01T10:00:30Z','value':2,'sample_count':1}],
            'missing_intervals':[{'start':'2026-09-01T10:00:30Z','end':'2026-09-01T10:01:00Z'}]})})
    timeline = build_timeline(result)
    assert timeline['timezone'] == 'UTC'
    events = timeline['events']
    assert [e['kind'] for e in events] == ['change','alert_start','alert_trigger','metric_sample','metric_gap','log','alert_end']
    assert events[0]['collection_order'] == 2 and events[-2]['collection_order'] == 1
    assert events[-2]['start'] == '2026-09-01T10:02:00Z'
    assert events[3]['end'] == '2026-09-01T10:00:30Z'
    assert timeline['scope']['snapshot_window']['start'] == '2026-09-01T09:50:00Z'


async def test_adaptive_demo_retains_context_without_exceeding_default_request_budget():
    result = await run_investigation(demo_case(), ScriptedProvider(), workflow='adaptive')
    assert result.get('hypotheses') and result.get('timeline')
    assert result['report']['status'] == 'diagnosis'
    for prompt in result['prompts']:
        contract = Decision if prompt['contract'] == 'Decision' else __import__('investigator.contracts',fromlist=['Report']).Report
        assert AnthropicProvider.estimate_input(prompt['payload'], contract) < 30000


def test_trace_timeline_preserves_span_duration_and_identity():
    from investigator.timeline import build_timeline
    result = dict(evidence={'span':dict(source_kind='traces', payload={
        'start_time':'2026-09-01T18:00:00.250+08:00','end_time':'2026-09-01T18:00:01+08:00',
        'trace_id':'trace-1','span_id':'span-1','operation':'shipping.request','service':'shipping'})})
    events = build_timeline(result)['events']
    assert len(events) == 1
    assert events[0]['kind'] == 'trace_span'
    assert events[0]['label'] == 'shipping.request'
    assert events[0]['start'] == '2026-09-01T10:00:00.250000Z'
    assert events[0]['end'] == '2026-09-01T10:00:01Z'
    assert events[0]['trace_id'] == 'trace-1' and events[0]['span_id'] == 'span-1'

def test_timeline_expanded_scope_is_query_interval_not_collection_time():
    from investigator.timeline import build_timeline
    result={'alert':{'window':{'start':'2026-09-01T10:00:00Z','end':'2026-09-01T10:05:00Z'}},'events':[
        {'tool':'query_traces','status':'partial','arguments':{'window':{'start':'2026-09-01T09:55:00Z','end':'2026-09-01T10:05:00Z'}}}], 'evidence':{}}
    timeline=build_timeline(result)
    assert timeline['scope']['expanded_windows']==[{'tool':'query_traces','start':'2026-09-01T09:55:00Z','end':'2026-09-01T10:05:00Z'}]
