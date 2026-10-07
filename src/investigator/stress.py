"""Handcrafted stress observations, deliberately separate from captured benchmarks.

These are synthetic software exercises without capture provenance or human labels.
"""
from copy import deepcopy
from .demo import demo_case


def stress_cases():
    descriptions={
        'simultaneous':'Simultaneous dependency timeouts and pool acquisition failures',
        'nearby-change':'Dependency failures near a deployment; causality unresolved',
        'intermittent':'Intermittent dependency failures mixed with successful orders',
        'incomplete':'Order failures with missing telemetry intervals',
        'healthy-lookalike':'Slow successful orders and warnings resemble a failure',
    }
    cases={}
    for name,description in descriptions.items():
        case=demo_case();key='stress-'+name
        case.update(opaque_case_id=key,source='handcrafted stress fixture')
        case['alert'].update(alert_id='a-'+key,symptom='Handcrafted stress: '+description)
        s=case['telemetry_snapshot'];s['snapshot_id']='s-'+key
        if name=='simultaneous':
            s['logs'].append(dict(source_record_id='l-pool',timestamp='2026-09-01T10:03:10Z',service='orders',level='error',event_code='pool_timeout',message='Database acquisition exceeded deadline',fields={}))
            for i,(metric,value) in enumerate([('db_pool_capacity',4),('db_pool_in_use',4),('db_pool_acquire_timeout_count',2)]):
                s['metrics'].append(dict(source_record_id=f'm-pool-{i}',timestamp='2026-09-01T10:03:10Z',service='orders',metric=metric,value=value,unit='count'))
        elif name=='nearby-change':
            # A timestamp is not evidence that the deployment caused the observed delay.
            s['changes']=[dict(source_record_id='change-nearby',timestamp='2026-09-01T10:02:55Z',service='orders',revision='handcrafted-nearby-deployment',changed={'dependency_path':{'old':'/quote','new':'/quote'}},rollout_scope='orders')]
        elif name=='intermittent':
            s['logs']=[];s['metrics']=[]
            for i in range(6):
                failed=i%2==1;stamp=f'2026-09-01T10:0{1+i//3}:{(i%3)*20:02d}Z'
                s['logs'].append(dict(source_record_id=f'l-intermittent-{i}',timestamp=stamp,service='orders',level='error' if failed else 'info',event_code='dependency_timeout' if failed else 'request_ok',message='Shipping deadline exceeded' if failed else 'Order completed',fields={}))
                for metric,value,unit in [('dependency_timeout_count',int(failed),'count'),('dependency_duration_p95',510 if failed else 35,'ms'),('request_count',1,'count')]:
                    s['metrics'].append(dict(source_record_id=f'm-{i}-{metric}',timestamp=stamp,service='orders',metric=metric,value=value,unit=unit))
        elif name=='incomplete':
            s['complete']=False;s['metrics']=[]
        elif name=='healthy-lookalike':
            s['logs']=[dict(source_record_id='l-success',timestamp='2026-09-01T10:03:00Z',service='orders',level='info',event_code='request_ok',message='Order completed with elevated duration',fields={}),dict(source_record_id='l-warning',timestamp='2026-09-01T10:03:01Z',service='orders',level='warning',event_code='auth_warning',message='Authentication retry succeeded',fields={})]
            s['metrics']=[dict(source_record_id=f'm-healthy-{i}',timestamp='2026-09-01T10:03:00Z',service='orders',metric=metric,value=value,unit=unit) for i,(metric,value,unit) in enumerate([('dependency_duration_p95',480,'ms'),('request_count',1,'count'),('error_count',0,'count'),('dependency_timeout_count',0,'count')])]
        cases[key]=case
    return deepcopy(cases)
