"""Explicitly handcrafted development fixture. Not capture-backed benchmark data."""
from copy import deepcopy


def demo_case(missing=False):
    window = {'start': '2026-09-01T09:55:00Z', 'end': '2026-09-01T10:05:00Z'}
    snapshot = {'snapshot_id': 's-7ac982', 'window': window, 'complete': not missing,
                'logs': [], 'metrics': [], 'changes': [], 'runbooks': []}
    if not missing:
        snapshot['logs'] = [dict(source_record_id='l-017', timestamp='2026-09-01T10:03:00Z',
                                service='orders', level='error', event_code='dependency_timeout',
                                message='Shipping request exceeded deadline', fields={'timeout_ms': 1000})]
        for i, (name, value, unit) in enumerate([('dependency_timeout_count', 7, 'count'),
                    ('db_query_duration_p95', 4, 'ms'), ('dependency_duration_p95', 1002, 'ms')]):
            snapshot['metrics'].append(dict(source_record_id=f'm-{i}', timestamp='2026-09-01T10:03:00Z',
                service='orders', metric=name, value=value, unit=unit))
    return deepcopy({'opaque_case_id': 'c-31f09a', 'alert': dict(alert_id='a-123', service='orders',
        triggered_at=window['end'], window=window, symptom='Order request error rate increased'),
        'telemetry_snapshot': snapshot, 'runbook_version': 'v1'})


def approval_demo_case():
    case = demo_case()
    case['opaque_case_id'] = 'demo-approval'
    case['alert']['alert_id'] = 'a-approval-demo'
    case['alert']['symptom'] = 'Approval and restart demonstration: inspect earlier dependency observations'
    case['telemetry_snapshot']['window'] = {'start':'2026-09-01T09:50:00Z','end':'2026-09-01T10:05:00Z'}
    case['telemetry_snapshot']['snapshot_id'] = 's-approval-demo'
    return case


def trace_demo_case():
    """Handcrafted parent/child spans; these are not a capture or quality label."""
    case=demo_case()
    case['opaque_case_id']='demo-traces'
    case['alert'].update(alert_id='a-traces-demo',symptom='Handcrafted trace demonstration: shipping deadline exceeded')
    snapshot=case['telemetry_snapshot'];snapshot['snapshot_id']='s-traces-demo'
    specs=[('1',None,'orders','orders.request','00','02','error'),
           ('2','1','orders','database.query','00','00.010000','ok'),
           ('3','1','orders','shipping.request','00.020000','01','error'),
           ('4','3','shipping','shipping.quote','00.030000','01.500000','ok')]
    snapshot['traces']=[dict(source_record_id='handcrafted-span-'+key,trace_id='a'*32,span_id=key*16,
        parent_span_id=parent*16 if parent else None,service=service,operation=operation,
        start_time='2026-09-01T10:03:'+start+'Z',end_time='2026-09-01T10:03:'+end+'Z',status=status)
        for key,parent,service,operation,start,end,status in specs]
    snapshot['traces_complete']=True
    return case
