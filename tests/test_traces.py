from copy import deepcopy
import pytest
from investigator.demo import demo_case
from investigator.snapshot import Snapshot
from investigator.telemetry import Telemetry
from investigator.contracts import ToolRequest


def span(**updates):
    return dict(source_record_id='span-1', trace_id='1'*32, span_id='2'*16,
        parent_span_id=None, service='orders', operation='orders.request',
        start_time='2026-09-01T10:03:00Z', end_time='2026-09-01T10:03:01Z', status='ok', **updates)


def request(**updates):
    return ToolRequest(tool='query_traces', arguments=({'service':'orders','window':demo_case()['alert']['window']} | updates))


async def test_missing_trace_capture_is_partial_and_legacy_serialization_stable():
    snap = demo_case()['telemetry_snapshot']
    before = Snapshot.model_validate(snap).model_dump(mode='json', exclude_none=True)
    assert 'traces' not in before and 'traces_complete' not in before
    result = await Telemetry(snap).query(request())
    assert result['status'] == 'partial' and not result['coverage']['complete']


async def test_trace_query_bounded_correlated_and_stable():
    snap = demo_case()['telemetry_snapshot']
    first = span()
    second = {**first, 'source_record_id':'span-2','span_id':'3'*16,'parent_span_id':'2'*16, 'operation':'database.query'}
    snap.update(traces=[first,second], traces_complete=True)
    adapter = Telemetry(snap)
    result = await adapter.query(request(limit=1))
    assert result['truncated'] and result['total_matches'] == 2
    again = await adapter.query(request(trace_id='1'*32))
    assert result['evidence_ids'][0] == again['evidence_ids'][0]
    assert again['items'][1]['payload']['parent_span_id'] == '2'*16
    assert (await adapter.query(request(service='shipping')))['status'] == 'empty'


@pytest.mark.parametrize('updates', [dict(service='database'),dict(limit=101),dict(trace_id='0'*32),dict(sql='SELECT 1'),dict(window={'start':'2026-09-01T09:00:00Z','end':'2026-09-01T09:01:00Z'})])
async def test_trace_query_rejects_unbounded_or_unsafe_arguments(updates):
    args = request().arguments | updates
    with pytest.raises(ValueError): await Telemetry(demo_case()['telemetry_snapshot']).query(ToolRequest(tool='query_traces',arguments=args))


@pytest.mark.parametrize('updates', [dict(sql='SELECT secret'),dict(operation='DROP TABLE'),dict(trace_id='0'*32),dict(end_time='2026-09-01T10:02:00Z'),dict(status='healthy')])
def test_snapshot_rejects_unsanitized_spans(updates):
    snap=demo_case()['telemetry_snapshot']; snap['traces']=[span() | updates]
    with pytest.raises(ValueError): Snapshot.model_validate(snap)


def test_recorder_preserves_w3c_relationships_and_sanitizes():
    from environment.tracing import LocalTracing
    orders, shipping = LocalTracing('orders', capacity=2), LocalTracing('shipping')
    with orders.span('orders.request'):
        with orders.span('shipping.request'):
            headers=orders.headers()
            with shipping.span('shipping.quote', headers=headers): pass
    left,right=orders.snapshot(),shipping.snapshot()
    assert left['complete'] and right['complete']
    client=next(s for s in left['spans'] if s['operation']=='shipping.request')
    server=right['spans'][0]
    assert server['trace_id']==client['trace_id'] and server['parent_span_id']==client['span_id']
    assert set(server)==set(span())
    with orders.span('database.query'): pass
    assert not orders.snapshot()['complete'] and len(orders.snapshot()['spans'])==2
    with pytest.raises(ValueError):
        with orders.span('secret sql'): pass


def test_in_flight_spans_and_capture_cutoff_are_incomplete():
    from environment.tracing import LocalTracing, freeze_traces
    recorder=LocalTracing('orders')
    with recorder.span('orders.request'):
        import time
        time.sleep(.002)
        assert recorder.snapshot()['complete'] is False
    raw=recorder.snapshot()
    assert raw['complete']
    first=raw['spans'][0]
    frozen=freeze_traces([raw,{'spans':[],'complete':True}],{'start':first['start_time'],'end':first['end_time']})
    assert len(frozen['traces'])==1
    assert frozen['traces_complete']
    partial=freeze_traces([raw,{'spans':[],'complete':True}],{'start':first['start_time'],'end':first['start_time']})
    assert not partial['traces_complete']

async def test_trace_expansion_requires_exact_approval(tmp_path):
    from investigator.checkpoint import Investigations
    from investigator.provider import ScriptedProvider
    from investigator.demo import approval_demo_case
    class Expanded(ScriptedProvider):
        async def respond(self,context,contract,max_tokens,timeout):
            if contract.__name__=='Decision' and not any(e.get('tool')=='query_traces' for e in context['tool_events']):
                return {'action':'collect','summary':'Collect earlier trace spans','tool_request':{'tool':'query_traces','arguments':{'service':'orders','window':context['query_window']}}},{'input_tokens':0,'output_tokens':0,'cache_tokens':0}
            if contract.__name__=='Decision':
                return {'action':'report','summary':'Summarize trace evidence'},{'input_tokens':0,'output_tokens':0,'cache_tokens':0}
            return await super().respond(context,contract,max_tokens,timeout)
    service=Investigations(tmp_path/'trace.sqlite',Expanded())
    case=approval_demo_case();case['telemetry_snapshot'].update(traces=[span()],traces_complete=True)
    run=service.create(case);paused=await service.drive(run)
    assert paused['state']=='awaiting_approval'
    assert paused['result']['usage']['tool_dispatches']==0
    resumed=await service.drive(run,approval={**paused['pending_approval']['token'],'decision':'approve'})
    assert resumed['state']=='finished'
    assert resumed['result']['usage']['tool_dispatches']==1
    assert any(e['source_kind']=='traces' for e in resumed['result']['evidence'].values())

async def test_shipping_trace_service_and_query_window_do_not_leak_later_span_time():
    snap=demo_case()['telemetry_snapshot']
    ship=span() | {'service':'shipping','operation':'shipping.quote'}
    snap.update(traces=[ship],traces_complete=True)
    result=await Telemetry(snap).query(request(service='shipping'))
    assert result['items'][0]['service']=='shipping'
    narrow=request(service='shipping',window={'start':'2026-09-01T10:02:59Z','end':'2026-09-01T10:03:00.500000Z'})
    result=await Telemetry(snap).query(narrow)
    assert result['items']==[] and result['status']=='partial'


def test_snapshot_rejects_trace_outside_frozen_horizon():
    snap=demo_case()['telemetry_snapshot'];snap['traces']=[span() | {'end_time':'2026-09-01T10:06:00Z'}]
    with pytest.raises(ValueError): Snapshot.model_validate(snap)

async def test_scripted_trace_demonstration_collects_both_services():
    from investigator.demo import trace_demo_case
    from investigator.provider import ScriptedProvider
    from investigator.runner import run_investigation
    result=await run_investigation(trace_demo_case(),ScriptedProvider(),workflow='adaptive')
    traces=[e for e in result['evidence'].values() if e['source_kind']=='traces']
    assert {e['service'] for e in traces}=={'orders','shipping'}
    assert any(e['kind']=='trace_span' for e in result['timeline']['events'])
    assert result['usage']['estimated_cost_usd']==0

def test_recorder_restart_during_requested_window_is_missing_evidence():
    from environment.tracing import LocalTracing, freeze_traces
    recording=LocalTracing('orders').snapshot()
    assert recording.get('started_at')
    result=freeze_traces([recording,recording],{'start':'2026-01-01T00:00:00Z','end':'2027-01-01T00:00:00Z'})
    assert result['traces_complete'] is False
