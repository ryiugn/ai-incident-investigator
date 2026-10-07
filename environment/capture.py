"""Separate controller: reset -> baseline -> fault -> snapshot -> cleanup -> recovery.

No module in src/investigator imports this module or knows its control URLs.
"""
import argparse
import json
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
import httpx
import psycopg
from .tracing import freeze_traces

ORDERS = 'http://127.0.0.1:18080'
SHIPPING = 'http://127.0.0.1:18081'
DSN = 'postgresql://investigator_demo:local_demo_only@127.0.0.1:55432/orders'
FAMILIES = ('dependency_timeout', 'lock_contention', 'pool_exhaustion', 'slow_query', 'config_error')


def now():
    return datetime.now(timezone.utc).isoformat()


def values(snapshot, metric):
    return [r['value'] for r in snapshot['metrics'] if r['metric'] == metric]


def capture(family, seed=17):
    if family not in FAMILIES: raise ValueError('unknown fault')
    rng = random.Random(seed)
    capture_id = uuid.uuid4().hex
    lock = None
    healthy = fault = cleanup = False
    with httpx.Client(timeout=8) as client, psycopg.connect(DSN, autocommit=True) as db:
        def reset():
            client.post(SHIPPING+'/control', json={'delay_ms':0}).raise_for_status()
            client.post(ORDERS+'/control', json={'dependency_path':'/quote','hold_connections':False}).raise_for_status()
            db.execute('CREATE INDEX IF NOT EXISTS inventory_sku_idx ON inventory(sku)')
        def traffic(count):
            return [client.post(ORDERS+'/orders', params={'sku':rng.randint(100000,300000)}).status_code for _ in range(count)]
        def service_time():
            response=client.get(ORDERS+'/clock')
            response.raise_for_status()
            return response.json()['timestamp']
        reset()
        start = service_time()
        healthy = all(status == 200 for status in traffic(4))
        if not healthy: raise RuntimeError('healthy baseline failed')
        baseline = client.get(ORDERS+'/telemetry').json()
        baseline_values = [r['value'] for r in baseline['metrics'] if r['metric']=='db_query_duration_p95' and r['timestamp'] >= start]
        activation = service_time()
        try:
            if family == 'dependency_timeout':
                client.post(SHIPPING+'/control', json={'delay_ms':rng.randint(850,1200)}).raise_for_status()
            elif family == 'config_error':
                client.post(ORDERS+'/control', json={'dependency_path':'/quotes-invalid'}).raise_for_status()
            elif family == 'pool_exhaustion':
                client.post(ORDERS+'/control', json={'hold_connections':True}).raise_for_status()
            elif family == 'slow_query':
                db.execute('DROP INDEX IF EXISTS inventory_sku_idx')
            elif family == 'lock_contention':
                lock = psycopg.connect(DSN)
                lock.execute('UPDATE inventory SET stock=stock WHERE id=1')
            statuses = traffic(6)
            cutoff = service_time()
            raw = client.get(ORDERS+'/telemetry').json()
            trace_recordings=[]
            for service_url in (ORDERS,SHIPPING):
                try:
                    response=client.get(service_url+'/traces')
                    response.raise_for_status()
                    trace_recordings.append(response.json())
                except (httpx.HTTPError,ValueError):
                    trace_recordings.append({'spans':[],'complete':False})
            frozen_traces=freeze_traces(trace_recordings,{'start':start,'end':cutoff})
            snapshot = {kind:[r for r in rows if start <= r['timestamp'] < cutoff] for kind,rows in raw.items()}
            incident = {kind:[r for r in rows if activation <= r['timestamp'] < cutoff] for kind,rows in raw.items()}
            codes = {r['event_code'] for r in incident['logs']}
            if family == 'dependency_timeout': fault = 'dependency_timeout' in codes and max(values(incident,'dependency_timeout_count'),default=0)>0
            elif family == 'config_error': fault = 'dependency_error' in codes and bool(incident['changes'])
            elif family == 'pool_exhaustion': fault = 'pool_timeout' in codes and max(values(incident,'db_pool_in_use'),default=0)==4
            elif family == 'lock_contention': fault = 'db_timeout' in codes and max(values(incident,'db_lock_wait_count'),default=0)>0
            elif family == 'slow_query': fault = max(values(incident,'db_query_duration_p95'),default=0)>max(5, 2*max(baseline_values,default=1))
            if not fault: raise RuntimeError(f'Capture did not establish intended observable signature: {family}')
        finally:
            if lock is not None:
                lock.rollback(); lock.close()
            reset()
            cleanup = all(status == 200 for status in traffic(3))
            if not cleanup: raise RuntimeError('fault cleanup did not restore successful requests')
        snapshot.update(**frozen_traces)
        snapshot.update(snapshot_id=uuid.uuid4().hex, window={'start':start,'end':cutoff}, complete=True,
                        runbooks=load_runbooks())
        errors = sum(s != 200 for s in statuses)
        symptom = 'Order request error rate increased' if errors else 'Order request latency increased'
        case = dict(opaque_case_id=uuid.uuid4().hex, alert=dict(alert_id=uuid.uuid4().hex, service='orders',
            triggered_at=cutoff, window={'start':activation,'end':cutoff}, symptom=symptom),
            telemetry_snapshot=snapshot, runbook_version='v1')
        label = dict(case_id=case['opaque_case_id'], family=family, generation_group_id=capture_id,
            split='development', true_cause=family, answerability='answerable',
            maximum_supported_diagnostic_level='root_cause' if family=='config_error' else 'condition',
            acceptable_diagnoses={
              'dependency_timeout':['shipping dependency timeouts; underlying delay cause unknown'],
              'lock_contention':['database statements blocked by locks'],
              'pool_exhaustion':['database pool acquisition exhaustion; leak not established'],
              'slow_query':['slow database query execution; missing index not established'],
              'config_error':['changed shipping path matches HTTP errors']}[family],
            required_evidence_predicates=['Incident-window log/metric signature plus distinguishing evidence; address contrary observations'],
            forbidden_claims=['Knowledge of injected controls', 'Connection leak without lifetime evidence', 'Missing index without plan/index evidence'],
            expected_abstention=False, useful_action_classes=['inspect missing causal evidence'],
            failure_schedule=[], label_version='v1', review_status='pending_human_audit',
            provenance=dict(capture_id=capture_id, seed=seed, healthy_verified=healthy, fault_verified=fault,
                            cleanup_verified=cleanup, baseline_query_ms=baseline_values, captured_at=cutoff, transformations=[]))
        return case, label


def load_runbooks():
    root = Path(__file__).resolve().parents[1] / 'runbooks'
    return [dict(source_record_id=p.stem, document_id=p.stem, version='v1', section='Troubleshooting', text=p.read_text()) for p in sorted(root.glob('*.md'))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('family', choices=FAMILIES)
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--output', type=Path, default=Path('captures'))
    args = parser.parse_args()
    case,label = capture(args.family,args.seed)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'case.json').write_text(json.dumps(case,indent=2))
    (args.output/'private-label.json').write_text(json.dumps(label,indent=2))
    print(json.dumps({'case_id':case['opaque_case_id'],'verification':label['provenance']}))


if __name__ == '__main__': main()
