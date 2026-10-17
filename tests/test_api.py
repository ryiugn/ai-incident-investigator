import time
from fastapi.testclient import TestClient


def test_poll_does_not_replace_newer_worker_completion(monkeypatch,tmp_path):
    import asyncio
    import threading
    import investigator.api as api_module
    from investigator.api import create_app
    from investigator.checkpoint import Investigations
    from investigator.provider import ScriptedProvider
    entered, release = threading.Event(), threading.Event()
    class Delayed(ScriptedProvider):
        async def respond(self,*args):
            entered.set()
            while not release.is_set(): await asyncio.sleep(.01)
            return await super().respond(*args)
    original=Investigations.inspect
    saved=threading.Event()
    stale_returned=threading.Event()
    original_save=api_module.save_run
    def observe_save(path,value):
        original_save(path,value)
        if value.get('state')=='finished': saved.set()
    monkeypatch.setattr(api_module,'save_run',observe_save)
    async def overlapping(self,run_id,active=None):
        snapshot=await original(self,run_id,active)
        if active is not False and snapshot['state']=='running':
            release.set()
            # Hold an old poll response until the real worker publishes completion.
            for _ in range(1000):
                if saved.is_set():
                    stale_returned.set()
                    return snapshot
                await asyncio.sleep(.01)
        return snapshot
    monkeypatch.setattr(Investigations,'inspect',overlapping)
    with TestClient(create_app(archive=tmp_path,provider=Delayed())) as client:
        run_id=client.post('/api/runs',json={'case_id':'demo','workflow':'adaptive'}).json()['run_id']
        assert entered.wait(5)
        result=client.get('/api/runs/'+run_id).json()
        assert stale_returned.is_set()
        assert result['state']=='finished'
        assert result['result']['report']


def test_start_poll_evidence_and_reject_unknown_ids(tmp_path):
    from investigator.api import create_app
    with TestClient(create_app(archive=tmp_path)) as client:
        assert client.post('/api/runs',json={'case_id':'../../secret','workflow':'fixed'}).status_code==404
        response=client.post('/api/runs',json={'case_id':'demo','workflow':'adaptive'})
        assert response.status_code==202
        run_id=response.json()['run_id']
        for _ in range(100):
            result=client.get('/api/runs/'+run_id).json()
            if result['state']=='finished': break
            time.sleep(.02)
        assert result['state']=='finished'
        assert 'prompts' not in result['result']
        evidence_id=next(iter(result['result']['evidence']))
        assert client.get(f'/api/runs/{run_id}/evidence/{evidence_id}').status_code==200
        assert client.get(f'/api/runs/{run_id}/evidence/unknown').status_code==404
        assert client.post('/api/runs',json={'case_id':'demo','workflow':'fixed','api_key':'secret'}).status_code==422


def test_restart_marks_unfinished_jobs_interrupted(tmp_path):
    from investigator.api import create_app
    import json
    (tmp_path/'jobs').mkdir()
    (tmp_path/'jobs'/'123.json').write_text(json.dumps({'run_id':'123','state':'running','result':None}))
    with TestClient(create_app(archive=tmp_path)) as client:
        assert client.get('/api/runs/123').json()['state']=='interrupted'


def test_new_live_capture_is_selectable_without_restart(tmp_path):
    from investigator.api import create_app
    from investigator.demo import demo_case
    import json
    captured=tmp_path/'captures'
    with TestClient(create_app(archive=tmp_path/'archive',captured=captured)) as client:
        (captured/'latest').mkdir(parents=True)
        case=demo_case(); case['opaque_case_id']='new-live-capture'
        (captured/'latest'/'case.json').write_text(json.dumps(case))
        assert any(c['case_id']=='new-live-capture' for c in client.get('/api/cases').json())


def test_config_exposes_provider_name_without_credentials(tmp_path):
    from investigator.api import create_app
    from investigator.provider import ScriptedProvider
    provider=ScriptedProvider(); provider.name='custom-offline'; provider.secret='NEVER_EXPOSE'
    with TestClient(create_app(archive=tmp_path,provider=provider)) as client:
        config=client.get('/api/config').json()
        assert config['provider']=='custom-offline'
        assert 'NEVER_EXPOSE' not in str(config)


async def test_restart_keeps_pending_approval_visible_above_eight_finished_runs(tmp_path):
    import os
    import httpx
    from investigator.api import create_app
    from investigator.archive import save_run
    from investigator.checkpoint import Investigations
    from investigator.demo import approval_demo_case
    from investigator.provider import ApprovalDemoProvider
    provider = ApprovalDemoProvider()
    service = Investigations(tmp_path/'checkpoints.sqlite',provider)
    run_id = service.create(approval_demo_case(),run_id='000-pending')
    save_run(tmp_path/'jobs',await service.drive(run_id))
    for i in range(10):
        key = f'finished-{9-i}'
        save_run(tmp_path/'jobs',dict(run_id=key,state='finished',workflow='fixed',result=None))
        os.utime(tmp_path/'jobs'/f'{key}.json',(1700000000+i,1700000000+i))
    app = create_app(archive=tmp_path,provider=provider)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            runs = (await client.get('/api/runs')).json()
            assert runs[0]['run_id'] == run_id
            assert runs[0]['state'] == 'awaiting_approval'
            assert runs[1]['run_id'] == 'finished-0'
            assert (await client.get(f'/api/runs/{run_id}/approval')).status_code == 200


def test_recent_runs_sort_by_saved_creation_time_not_archive_filename(tmp_path):
    from investigator.api import create_app
    from investigator.archive import save_run
    save_run(tmp_path/'jobs',dict(run_id='aaa-newest',state='finished',workflow='fixed',result=None,created_at=200))
    save_run(tmp_path/'jobs',dict(run_id='zzz-oldest',state='finished',workflow='fixed',result=None,created_at=100))
    with TestClient(create_app(archive=tmp_path)) as client:
        assert [r['run_id'] for r in client.get('/api/runs').json()] == ['aaa-newest','zzz-oldest']
