"""Opt-in real HTTP + PostgreSQL trace integration on an isolated local stack."""
import os
import time
from datetime import datetime,timedelta
import httpx
import pytest

@pytest.mark.live
@pytest.mark.skipif(not os.environ.get('TRACE_ORDERS_URL'),reason='isolated trace stack not configured')
def test_real_orders_database_shipping_trace_chain():
    orders=os.environ['TRACE_ORDERS_URL'];shipping=os.environ['TRACE_SHIPPING_URL']
    with httpx.Client(timeout=10) as client:
        client.post(shipping+'/control',json={'delay_ms':0}).raise_for_status()
        client.post(orders+'/orders').raise_for_status()
        a=client.get(orders+'/traces'); b=client.get(shipping+'/traces')
        assert a.status_code==200 and b.status_code==200
        spans=a.json()['spans']+b.json()['spans']
        roots=[s for s in spans if s['operation']=='orders.request']
        assert roots
        root=roots[-1];chain=[s for s in spans if s['trace_id']==root['trace_id']]
        by_op={s['operation']:s for s in chain}
        assert {'orders.request','database.acquire','database.query','shipping.request','shipping.quote'}<=set(by_op)
        assert by_op['database.query']['parent_span_id']==root['span_id']
        assert by_op['shipping.request']['parent_span_id']==root['span_id']
        assert by_op['shipping.quote']['parent_span_id']==by_op['shipping.request']['span_id']
        assert all(s['status']=='ok' for s in chain)
        assert all(set(s)=={'source_record_id','trace_id','span_id','parent_span_id','service','operation','start_time','end_time','status'} for s in chain)
        from environment.tracing import freeze_traces
        from investigator.snapshot import Snapshot
        from investigator.telemetry import Telemetry
        from investigator.demo import demo_case
        end=max(s['end_time'] for s in chain)
        frozen=freeze_traces([a.json(),b.json()],{'start':root['start_time'],'end':end})
        assert frozen['traces_complete']
        case=demo_case();case['telemetry_snapshot'].update(window={'start':root['start_time'],'end':end},logs=[],metrics=[],**frozen)
        Snapshot.model_validate(case['telemetry_snapshot'])
        client.post(shipping+'/control',json={'delay_ms':900}).raise_for_status()
        try:
            assert client.post(orders+'/orders').status_code==503
            assert not client.get(shipping+'/traces').json()['complete']
            time.sleep(.6)
            errors=client.get(orders+'/traces').json()['spans']
            assert any(s['operation']=='shipping.request' and s['status']=='error' for s in errors)
        finally:
            client.post(shipping+'/control',json={'delay_ms':0}).raise_for_status()
