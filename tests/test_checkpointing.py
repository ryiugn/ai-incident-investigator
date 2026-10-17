import asyncio
import importlib.util
import json
import pytest
from investigator.demo import demo_case
from investigator.provider import ScriptedProvider
from investigator.telemetry import Telemetry


def service(path, provider=None, adapter_factory=Telemetry):
    assert importlib.util.find_spec('investigator.checkpoint'), 'Durable investigation service is missing'
    from investigator.checkpoint import Investigations
    return Investigations(path, provider or ExpansionProvider(), adapter_factory=adapter_factory)


def expanded_case():
    case = demo_case()
    case['telemetry_snapshot']['window']['start'] = '2026-09-01T09:50:00Z'
    # demo_case shares the window object; explicitly keep the original alert narrow.
    case['alert']['window'] = {'start':'2026-09-01T09:55:00Z','end':'2026-09-01T10:05:00Z'}
    return case


class ExpansionProvider(ScriptedProvider):
    name = 'offline-expansion-test'
    def __init__(self):
        self.calls = []
    async def respond(self, context, contract, max_tokens, timeout):
        self.calls.append(contract.__name__)
        if contract.__name__ == 'Decision':
            events = [e for e in context['tool_events'] if 'tool' in e]
            if len(events) == 0:
                tool, args = 'query_logs', {'levels':['error'], 'window':context['alert']['window']}
            elif len(events) == 1:
                tool, args = 'query_metrics', {'metric_names':['dependency_timeout_count'],
                    'window':context['query_window'], 'step_seconds':30}
            else:
                return {'action':'report','summary':'Enough observations.','tool_request':None}, dict(input_tokens=2,output_tokens=1,cache_tokens=0)
            return {'action':'collect','summary':'Compare earlier observations.',
                    'tool_request':{'tool':tool,'arguments':{'service':'orders',**args}}}, dict(input_tokens=2,output_tokens=1,cache_tokens=0)
        return await super().respond(context, contract, max_tokens, timeout)


class RecordingTelemetry(Telemetry):
    queries = []
    async def query(self, request):
        self.queries.append(request.model_dump(mode='json'))
        return await super().query(request)


async def paused(tmp_path):
    RecordingTelemetry.queries = []
    svc = service(tmp_path/'checkpoint.sqlite', adapter_factory=RecordingTelemetry)
    run_id = svc.create(expanded_case(), case_id='expanded')
    job = await svc.drive(run_id)
    assert job['state'] == 'awaiting_approval'
    assert len(RecordingTelemetry.queries) == 1
    assert job['result']['usage']['model_requests'] == 2
    assert job['result']['usage']['tool_dispatches'] == 1
    assert job['result']['evidence']
    return svc, run_id, job


async def test_pause_then_fresh_service_approves_exact_query_without_repeating_work(tmp_path):
    svc, run_id, before = await paused(tmp_path)
    pending = before['pending_approval']
    assert pending['query']['tool'] == 'query_metrics'
    assert pending['requested_window']['start'].startswith('2026-09-01T09:50')
    provider = ExpansionProvider()
    fresh = service(tmp_path/'checkpoint.sqlite', provider, RecordingTelemetry)
    result = await fresh.drive(run_id, approval={**pending['token'], 'decision':'approve'})
    assert result['state'] == 'finished'
    assert len(RecordingTelemetry.queries) == 2
    assert RecordingTelemetry.queries[-1] == pending['query']
    assert provider.calls == ['Decision','Report']
    assert result['result']['usage']['model_requests'] == 4
    assert result['result']['usage']['tool_dispatches'] == 2
    assert set(before['result']['evidence']) <= set(result['result']['evidence'])
    assert result['result']['report']['likely_cause']['evidence_ids']
    assert result['run_id'] == result['result']['run_id'] == run_id


async def test_decline_skips_expansion_and_states_limitation(tmp_path):
    svc, run_id, job = await paused(tmp_path)
    result = await svc.drive(run_id, approval={**job['pending_approval']['token'],'decision':'decline'})
    assert result['state'] == 'finished'
    assert len(RecordingTelemetry.queries) == 1
    assert result['result']['termination_reason'] == 'approval_declined'
    assert any('declined' in s.lower() for s in result['result']['report']['missing_evidence'])


async def test_stale_duplicate_and_concurrent_approvals_are_rejected(tmp_path):
    svc, run_id, job = await paused(tmp_path)
    token = job['pending_approval']['token']
    with pytest.raises(ValueError, match='stale'):
        await svc.drive(run_id, approval={**token,'checkpoint_id':'old','decision':'approve'})
    results = await asyncio.gather(
        svc.drive(run_id, approval={**token,'decision':'approve'}),
        service(tmp_path/'checkpoint.sqlite',adapter_factory=RecordingTelemetry).drive(run_id, approval={**token,'decision':'approve'}),
        return_exceptions=True)
    assert sum(isinstance(r, ValueError) for r in results) == 1
    assert len(RecordingTelemetry.queries) == 2
    with pytest.raises(ValueError):
        await svc.drive(run_id, approval={**token,'decision':'approve'})


async def test_hard_scope_never_becomes_approvable(tmp_path):
    class Invalid(ExpansionProvider):
        async def respond(self, context, contract, *args):
            raw, tokens = await super().respond(context, contract, *args)
            if raw.get('tool_request'):
                raw['tool_request']['arguments']['window'] = {'start':'2026-09-01T09:40:00Z','end':'2026-09-01T10:05:00Z'}
            return raw, tokens
    svc = service(tmp_path/'checkpoint.sqlite', Invalid())
    job = await svc.drive(svc.create(expanded_case()))
    assert job['state'] == 'finished'
    assert job['result']['usage']['tool_dispatches'] == 0
    assert not job.get('pending_approval')


async def test_approval_wait_does_not_consume_execution_deadline(tmp_path):
    svc, run_id, job = await paused(tmp_path)
    before = job['result']['usage']['elapsed_ms']
    await asyncio.sleep(.15)
    still = await svc.inspect(run_id)
    assert still['result']['usage']['elapsed_ms'] == before
    finished = await svc.drive(run_id, approval={**job['pending_approval']['token'],'decision':'decline'})
    assert finished['result']['usage']['elapsed_ms'] - before < 150


def process(mode,tmp_path):
    import subprocess, sys, os
    from pathlib import Path
    env = {**os.environ,'PYTHONPATH':str(Path('src').resolve()) + os.pathsep + str(Path('tests').resolve())}
    return subprocess.run([sys.executable,'tests/checkpoint_process.py',mode,str(tmp_path/'checkpoint.sqlite'),str(tmp_path/'job.json')],
                          env=env,capture_output=True,text=True,timeout=20)


def test_separate_process_restart_preserves_evidence_budget_and_calls(tmp_path):
    first = process('pause',tmp_path)
    assert first.returncode == 0, first.stderr
    before = json.loads((tmp_path/'job.json').read_text())
    second = process('approve',tmp_path)
    assert second.returncode == 0, second.stderr
    after = json.loads((tmp_path/'job.json').read_text())
    assert before['state'] == 'awaiting_approval'
    assert after['state'] == 'finished'
    assert after['result']['usage']['input_tokens'] == 6
    assert after['result']['usage']['tool_dispatches'] == 2
    assert set(before['result']['evidence']) <= set(after['result']['evidence'])
    calls = [json.loads(s) for s in (tmp_path/'calls.jsonl').read_text().splitlines()]
    assert [c['kind'] for c in calls] == ['model','tool','model','tool','model','model']


@pytest.mark.parametrize('mode',['crash_model','crash_tool'])
def test_unknown_dispatch_keeps_reservations_and_cannot_replay(tmp_path,mode):
    first = process(mode,tmp_path)
    assert first.returncode == 17, first.stderr
    calls = (tmp_path/'calls.jsonl').read_text()
    second = process('uncertain',tmp_path)
    assert second.returncode == 0, second.stderr
    job = json.loads((tmp_path/'job.json').read_text())
    assert job['state'] == 'interrupted' and not job['resumable']
    completed = [s['node'] for s in job['result']['execution_steps']]
    assert ('triage' if mode == 'crash_model' else 'collect_evidence') not in completed
    assert 'Unknown external-call' in job['resume_error']
    usage = job['result']['usage']
    assert usage['model_requests'] == 1
    if mode == 'crash_model':
        assert usage['unknown_usage_reservations'][0]['reserved_cost_usd'] > 0
        assert usage['unknown_usage_reservations'][0]['output_tokens'] == 1000
    else:
        assert usage['tool_dispatches'] == 1
    assert (tmp_path/'calls.jsonl').read_text() == calls


def test_completed_node_journal_bridges_crash_before_graph_checkpoint(tmp_path):
    first = process('crash_after_node',tmp_path)
    assert first.returncode == 17, first.stderr
    second = process('recover',tmp_path)
    assert second.returncode == 0, second.stderr
    job = json.loads((tmp_path/'job.json').read_text())
    assert job['state'] == 'awaiting_approval'
    calls = [json.loads(s) for s in (tmp_path/'calls.jsonl').read_text().splitlines()]
    assert [c['kind'] for c in calls] == ['model','tool','model']


async def test_versions_provider_and_snapshot_binding_fail_closed(tmp_path):
    svc, run_id, job = await paused(tmp_path)
    changed = ExpansionProvider(); changed.name = 'different-model'
    with pytest.raises(ValueError, match='Provider'):
        await service(tmp_path/'checkpoint.sqlite',changed).drive(run_id,approval={**job['pending_approval']['token'],'decision':'approve'})
    with svc.db() as db:
        original = db.execute('SELECT state FROM investigations WHERE id=?',(run_id,)).fetchone()[0]
        state = json.loads(original); state['version'] = 999
        db.execute('UPDATE investigations SET state=? WHERE id=?',(json.dumps(state),run_id))
    with pytest.raises(ValueError,match='version'):
        await svc.drive(run_id)
    with svc.db() as db:
        state = json.loads(original); state['case']['telemetry_snapshot']['logs'] = []
        db.execute('UPDATE investigations SET state=? WHERE id=?',(json.dumps(state),run_id))
    with pytest.raises(ValueError,match='Snapshot'):
        await svc.drive(run_id)
    assert len(RecordingTelemetry.queries) == 1


async def test_approval_cannot_reset_tool_budget(tmp_path):
    from investigator.budgets import Limits
    svc = service(tmp_path/'checkpoint.sqlite')
    run_id = svc.create(expanded_case(),limits=Limits(tool_dispatches=1))
    job = await svc.drive(run_id)
    assert job['state'] == 'finished'
    assert not job['pending_approval']
    assert job['result']['usage']['tool_dispatches'] == 1
    assert job['result']['termination_reason'] == 'tool_budget'


def test_api_approval_survives_restart_and_rejects_replacement_arguments(tmp_path):
    import time
    from fastapi.testclient import TestClient
    from investigator.api import create_app
    public = tmp_path/'public'; public.mkdir()
    case = expanded_case(); case['opaque_case_id'] = 'expanded'
    (public/'expanded.json').write_text(json.dumps(case))
    def app(): return create_app(archive=tmp_path/'archive',public=public,provider=ExpansionProvider())
    with TestClient(app()) as client:
        run_id = client.post('/api/runs',json={'case_id':'expanded','workflow':'adaptive'}).json()['run_id']
        for _ in range(150):
            job = client.get('/api/runs/'+run_id).json()
            if job['state'] not in ('queued','running'): break
            time.sleep(.02)
        assert job['state'] == 'awaiting_approval'
    with TestClient(app()) as client:
        pending = client.get(f'/api/runs/{run_id}/approval').json()
        assert 'token' in pending
        body = {**pending['token'],'decision':'approve'}
        assert client.post(f'/api/runs/{run_id}/approval',json={**body,'arguments':{}}).status_code == 422
        assert client.post(f'/api/runs/{run_id}/approval',json=body).status_code == 200
        assert client.post(f'/api/runs/{run_id}/approval',json=body).status_code == 409
        job = client.get('/api/runs/'+run_id).json()
        assert job['state'] == 'finished'
        assert 'prompts' not in job['result']
        for evidence_id in job['result']['report']['likely_cause']['evidence_ids']:
            assert client.get(f'/api/runs/{run_id}/evidence/{evidence_id}').status_code == 200


async def test_missing_paid_ledger_cannot_reset_spending_on_resume(tmp_path):
    class PaidDouble(ExpansionProvider):
        paid = True
        ceiling = 1.0
        reserved_or_spent = 1.0
        ledger_path = tmp_path/'spend.json'
    provider = PaidDouble()
    svc = service(tmp_path/'checkpoint.sqlite',provider)
    run_id = svc.create(expanded_case())
    job = await svc.drive(run_id)
    assert job['result']['usage']['estimated_cost_usd'] > 0
    replacement = PaidDouble(); replacement.reserved_or_spent = 0
    with pytest.raises(ValueError,match='spending'):
        await service(tmp_path/'checkpoint.sqlite',replacement).drive(run_id,
            approval={**job['pending_approval']['token'],'decision':'approve'})


async def test_reservation_write_failure_prevents_model_dispatch(tmp_path):
    import sqlite3
    provider = ExpansionProvider()
    svc = service(tmp_path/'checkpoint.sqlite',provider)
    run_id = svc.create(expanded_case())
    original = svc.record
    def fail_reservation(*args):
        if args[3] == 'dispatching': raise sqlite3.OperationalError('read only')
        original(*args)
    svc.record = fail_reservation
    with pytest.raises(sqlite3.OperationalError):
        await svc.drive(run_id)
    assert provider.calls == []


def test_corrupt_store_rejects_new_adaptive_requests(tmp_path):
    from fastapi.testclient import TestClient
    from investigator.api import create_app
    (tmp_path/'checkpoints.sqlite').write_bytes(b'not sqlite')
    with TestClient(create_app(archive=tmp_path)) as client:
        assert client.post('/api/runs',json={'case_id':'demo','workflow':'adaptive'}).status_code == 503


async def test_state_only_carries_public_case_fields(tmp_path):
    svc = service(tmp_path/'checkpoint.sqlite')
    case = expanded_case(); case['private_label'] = 'DO_NOT_PERSIST'
    run_id = svc.create(case)
    await svc.drive(run_id)
    assert 'DO_NOT_PERSIST' not in json.dumps(svc.load(run_id))


async def test_separate_process_writer_blocks_resume_until_released(tmp_path):
    import os, subprocess, sys
    from pathlib import Path
    svc, run_id, job = await paused(tmp_path)
    code = "from investigator.checkpoint import writer_lock; import sys\nwith writer_lock(sys.argv[1]):\n print('locked',flush=True)\n sys.stdin.read(1)\n"
    child = subprocess.Popen([sys.executable,'-c',code,str(tmp_path/'checkpoint.sqlite')],
        env={**os.environ,'PYTHONPATH':str(Path('src').resolve())},stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip() == 'locked'
        with pytest.raises(ValueError,match='busy'):
            await svc.drive(run_id,approval={**job['pending_approval']['token'],'decision':'approve'})
    finally:
        child.communicate('x',timeout=10)
    finished = await svc.drive(run_id,approval={**job['pending_approval']['token'],'decision':'approve'})
    assert finished['state'] == 'finished'
    assert len(RecordingTelemetry.queries) == 2


@pytest.mark.parametrize('kind',['model','tool'])
async def test_response_loss_stops_without_retry_and_retains_full_reservation(tmp_path,kind):
    class LostModel(ExpansionProvider):
        paid = True
        async def respond(self,*args): raise TimeoutError('response lost')
    class LostTool(RecordingTelemetry):
        async def query(self,request):
            self.queries.append(request.model_dump(mode='json'))
            raise ConnectionError('response lost')
    RecordingTelemetry.queries = []
    svc = service(tmp_path/'checkpoint.sqlite', LostModel() if kind=='model' else ExpansionProvider(),
                  LostTool if kind=='tool' else Telemetry)
    run_id = svc.create(expanded_case())
    job = await svc.drive(run_id)
    assert job['state'] == 'interrupted' and not job['resumable']
    usage = job['result']['usage']
    assert usage['tool_retries'] == 0
    assert usage['elapsed_ms'] >= (20000 if kind=='model' else 3000)
    if kind=='model':
        assert usage['unknown_usage_reservations'][0]['reserved_cost_usd'] > 0
    else:
        assert len(RecordingTelemetry.queries) == 1
    with pytest.raises(ValueError): await svc.drive(run_id)


@pytest.mark.parametrize('mode',['crash_approval_receipt','crash_approval_node'])
def test_crash_after_approval_acceptance_recovers_without_duplicate_query(tmp_path,mode):
    assert process('pause',tmp_path).returncode == 0
    crash = process(mode,tmp_path)
    assert crash.returncode == 17, crash.stderr
    recovered = process('recover',tmp_path)
    assert recovered.returncode == 0, recovered.stderr
    job = json.loads((tmp_path/'job.json').read_text())
    assert job['state'] == 'finished'
    calls = [json.loads(s) for s in (tmp_path/'calls.jsonl').read_text().splitlines()]
    assert [c['kind'] for c in calls] == ['model','tool','model','tool','model','model']


def test_unsupported_store_version_fails_closed_in_api(tmp_path):
    from fastapi.testclient import TestClient
    from investigator.api import create_app
    svc = service(tmp_path/'checkpoints.sqlite')
    with svc.db() as db: db.execute('UPDATE investigation_meta SET version=999')
    with TestClient(create_app(archive=tmp_path)) as client:
        assert client.post('/api/runs',json={'case_id':'demo','workflow':'adaptive'}).status_code == 503


async def test_unavailable_store_does_not_show_stale_approval_from_job_archive(tmp_path):
    from investigator.archive import save_run
    from investigator.api import create_app
    import httpx
    svc = service(tmp_path/'checkpoints.sqlite')
    run_id = svc.create(expanded_case())
    job = await svc.drive(run_id)
    save_run(tmp_path/'jobs',job)
    (tmp_path/'checkpoints.sqlite').write_bytes(b'corrupt')
    app = create_app(archive=tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            saved = (await client.get('/api/runs/'+run_id)).json()
            assert saved['state'] == 'interrupted'
            assert saved['pending_approval'] is None
            assert not saved['resumable']
            assert 'unavailable' in saved['recovery_message'].lower()
