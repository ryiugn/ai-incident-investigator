import asyncio
import json
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .contracts import Contract
from .demo import demo_case, approval_demo_case, trace_demo_case
from .provider import ScriptedProvider
from .stress import stress_cases
from .runner import run_investigation
from .archive import save_run
from .checkpoint import Investigations
from .review import ReviewStore, ReviewSubmission, ReviewConflict
from .comparison import compare_runs


class Start(Contract):
    case_id: str
    workflow: Literal['fixed','adaptive'] = 'adaptive'


class Approval(Contract):
    approval_id: str
    checkpoint_id: str
    revision: int
    decision: Literal['approve','decline']


def create_app(archive=Path('archive'),public=Path('benchmark/public'),results=Path('benchmark/results'),ui=Path('ui/dist'),captured=Path('captures'),provider=None):
    archive,public,results=Path(archive),Path(public),Path(results)
    reviews=ReviewStore(archive/'reviews.sqlite')
    jobs={}
    queue=asyncio.Queue(maxsize=10)
    provider=provider or ScriptedProvider()
    investigations = None
    cases={'demo':demo_case(),'demo-missing':demo_case(missing=True),'demo-traces':trace_demo_case(),**stress_cases()}
    if provider.name == 'scripted-approval-v1': cases['demo-approval'] = approval_demo_case()
    for path in public.glob('*.json'):
        case=json.loads(path.read_text())
        cases[case['opaque_case_id']]=case
    jobdir=archive/'jobs'
    def save(job): save_run(jobdir,job)
    async def worker():
        while True:
            job_id,request=await queue.get()
            job=jobs[job_id]
            job['state']='running'; save(job)
            try:
                if request.workflow == 'adaptive':
                    job.update(await investigations.drive(job_id))
                    if job['state']=='finished': save_run(archive,job['result'])
                    continue
                result=await run_investigation(cases[request.case_id],provider,archive=archive,workflow=request.workflow)
                if asyncio.current_task().cancelling():
                    job.update(state='interrupted',result=None)
                    raise asyncio.CancelledError
                result.pop('prompts',None) # Full request archives stay on disk; UI shows observable actions only.
                job.update(state='finished',result=result)
            except asyncio.CancelledError:
                job.update(state='interrupted')
                raise
            except Exception:
                job.update(state='error',error='Investigation failed; inspect local service logs.')
            finally:
                save(job); queue.task_done()
    @asynccontextmanager
    async def lifespan(app):
        nonlocal investigations
        jobdir.mkdir(parents=True,exist_ok=True)
        for path in sorted(jobdir.glob('*.json'),key=lambda p:p.stat().st_mtime_ns):
            job=json.loads(path.read_text())
            job.setdefault('created_at',path.stat().st_mtime)
            if job['state'] in ('queued','running'): job['state']='interrupted'; save(job)
            jobs[job['run_id']]=job
        try:
            investigations = Investigations(archive/'checkpoints.sqlite',provider)
            for run_id in investigations.ids():
                try:
                    jobs[run_id] = {**jobs.get(run_id,{}), **await investigations.inspect(run_id)}
                except (ValueError,KeyError):
                    jobs[run_id] = dict(run_id=run_id,state='interrupted',workflow='adaptive',result=None,
                        resumable=False,recovery_message='Checkpoint is incompatible or damaged. Start a new investigation.')
        except (OSError,ValueError,sqlite3.Error):
            investigations = None
            for job in jobs.values():
                if job.get('workflow')=='adaptive' and job['state']!='finished':
                    job.update(state='interrupted',resumable=False,pending_approval=None,
                        recovery_message='Checkpoint store unavailable or incompatible. Restore the store before resuming, or start a new investigation after repair.')
        task=asyncio.create_task(worker())
        yield
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
    app=FastAPI(title='AI Incident Investigator',lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','testserver'])
    @app.middleware('http')
    async def local_origin(request:Request,call_next):
        from urllib.parse import urlparse
        from fastapi.responses import JSONResponse
        origin=request.headers.get('origin')
        if origin and urlparse(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail':'Cross-origin requests disabled'},status_code=403)
        return await call_next(request)
    @app.get('/api/cases')
    async def list_cases():
        from .telemetry import Telemetry
        for path in Path(captured).glob('*/case.json'):
            if path.stat().st_size>2_000_000: continue
            try:
                case=json.loads(path.read_text())
                Telemetry(case['telemetry_snapshot'])
                cases[case['opaque_case_id']]=case
            except (ValueError,KeyError): continue
        return [dict(case_id=key,symptom=case['alert']['symptom'],window=case['alert']['window'],
                     source='handcrafted stress fixture' if key.startswith('stress-') else 'handcrafted demonstration' if key.startswith('demo') else 'captured replay') for key,case in cases.items()]
    @app.get('/api/config')
    async def configuration():
        return {'provider':provider.name,'paid':provider.paid}
    @app.post('/api/runs',status_code=202)
    async def start(request:Start):
        if request.case_id not in cases: raise HTTPException(404,'Unknown case')
        if queue.full(): raise HTTPException(429,'Local queue full')
        run_id=uuid.uuid4().hex
        if request.workflow == 'adaptive':
            if investigations is None: raise HTTPException(503,'Checkpoint store unavailable; no investigation was dispatched.')
            try:
                investigations.create(cases[request.case_id],case_id=request.case_id,run_id=run_id)
            except (OSError,ValueError,sqlite3.Error):
                raise HTTPException(503,'Checkpoint store unavailable or configuration incompatible; no investigation was dispatched.')
        jobs[run_id]=dict(run_id=run_id,state='queued',result=None,case_id=request.case_id,workflow=request.workflow,created_at=time.time())
        save(jobs[run_id]); queue.put_nowait((run_id,request))
        return {'run_id':run_id}
    @app.get('/api/runs')
    async def list_runs():
        ordered = sorted(jobs.values(),key=lambda job:(job['state']!='awaiting_approval',-job.get('created_at',0)))
        return [{k:v for k,v in job.items() if k not in ('result','pending_approval')} for job in ordered]
    @app.get('/api/runs/{run_id}')
    async def get_run(run_id:str):
        if run_id not in jobs: raise HTTPException(404,'Unknown run')
        if investigations and jobs[run_id].get('workflow')=='adaptive' and jobs[run_id]['state']!='queued':
            original_job, original_state = jobs[run_id], jobs[run_id]['state']
            def unchanged():
                return jobs[run_id] is original_job and jobs[run_id]['state'] == original_state
            try:
                inspected = await investigations.inspect(run_id, active=True if original_state == 'running' else None)
                # A worker can finish while inspect awaits the graph checkpoint.
                # Do not overwrite its newer terminal/approval projection with an
                # older in-flight snapshot (which would stop browser polling).
                if unchanged():
                    jobs[run_id].update(inspected)
            except KeyError:
                if not unchanged(): return jobs[run_id]
                jobs[run_id].update(resumable=False,recovery_message='Legacy archive has no durable checkpoint. Start a new investigation.')
                if jobs[run_id]['state']!='finished': jobs[run_id].update(state='interrupted',pending_approval=None)
            except (ValueError,OSError,sqlite3.Error):
                if not unchanged(): return jobs[run_id]
                jobs[run_id].update(state='interrupted',resumable=False,pending_approval=None,
                    recovery_message='Checkpoint unavailable or incompatible. Restore the store/configuration or start a new investigation.')
        return jobs[run_id]

    async def reviewable(run_id):
        job=await get_run(run_id)
        if job['state']!='finished' or not (job.get('result') or {}).get('report'):
            raise HTTPException(409,'Review and comparison require a finished report.')
        return job['result']

    @app.get('/api/runs/{run_id}/review')
    async def get_review(run_id:str):
        return reviews.get(run_id,await reviewable(run_id))

    @app.post('/api/runs/{run_id}/review')
    async def save_review(run_id:str, request:ReviewSubmission):
        result=await reviewable(run_id)
        try:
            return reviews.save(run_id,result,request)
        except ReviewConflict as error:
            raise HTTPException(409,str(error))
        except ValueError as error:
            raise HTTPException(422,str(error))
        except (OSError,sqlite3.Error):
            raise HTTPException(503,'Review could not be saved; reload before retrying.')

    @app.get('/api/run-comparison')
    async def run_comparison(left:str,right:str):
        return compare_runs(left,await reviewable(left),right,await reviewable(right),reviews)

    @app.get('/api/runs/{run_id}/approval')
    async def pending_approval(run_id:str):
        job = await get_run(run_id)
        if not job.get('pending_approval'): raise HTTPException(409,'No pending approval; reload the investigation.')
        return job['pending_approval']

    async def continue_run(run_id, approval=None):
        await get_run(run_id)
        if investigations is None: raise HTTPException(503,'Checkpoint store unavailable.')
        try:
            job = {**jobs[run_id], **await investigations.drive(run_id, approval=approval)}
        except KeyError:
            raise HTTPException(409,'Legacy archive has no durable checkpoint. Start a new investigation.')
        except ValueError as error:
            raise HTTPException(409,str(error))
        except (OSError,sqlite3.Error):
            raise HTTPException(503,'Checkpoint write failed; reload recovery status before continuing.')
        jobs[run_id] = job
        save(job)
        if job['state']=='finished': save_run(archive,job['result'])
        return job

    @app.post('/api/runs/{run_id}/approval')
    async def submit_approval(run_id:str, request:Approval):
        return await continue_run(run_id,request.model_dump())

    @app.post('/api/runs/{run_id}/resume')
    async def resume(run_id:str):
        return await continue_run(run_id)
    @app.get('/api/runs/{run_id}/evidence/{evidence_id}')
    async def get_evidence(run_id:str,evidence_id:str):
        job=await get_run(run_id)
        evidence=(job.get('result') or {}).get('evidence',{})
        if evidence_id not in evidence: raise HTTPException(404,'Evidence not in this run')
        return evidence[evidence_id]
    @app.get('/api/comparisons')
    async def comparisons():
        # Never return labels, manifests, review maps or review packets.
        return [json.loads(p.read_text()) for p in sorted(results.glob('*/summary.json'))]
    if Path(ui).is_dir(): app.mount('/',StaticFiles(directory=ui,html=True),name='ui')
    return app


app=create_app()
