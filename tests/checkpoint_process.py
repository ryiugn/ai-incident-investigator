"""Separate-process fixture. All providers are offline doubles, including paid=True."""
import asyncio
import json
import os
import sys
from pathlib import Path
from investigator.checkpoint import Investigations, writer_lock
from test_checkpointing import ExpansionProvider, expanded_case
from investigator.telemetry import Telemetry

mode, dbpath, output = sys.argv[1:4]
root = Path(output).parent


class Provider(ExpansionProvider):
    paid = mode in ('crash_model','crash_tool','uncertain')
    async def respond(self, *args):
        with (root/'calls.jsonl').open('a') as f:
            f.write(json.dumps({'kind':'model','contract':args[1].__name__})+'\n')
        if mode == 'crash_model':
            os._exit(17)
        return await super().respond(*args)


class Adapter(Telemetry):
    async def query(self, request):
        with (root/'calls.jsonl').open('a') as f:
            f.write(json.dumps({'kind':'tool','query':request.model_dump(mode='json')})+'\n')
        if mode == 'crash_tool':
            os._exit(17)
        return await super().query(request)


async def main():
    svc = Investigations(dbpath,Provider(),Adapter)
    if mode in ('pause','crash_model','crash_tool','crash_after_node'):
        run_id = svc.create(expanded_case())
        Path(output).write_text(json.dumps({'run_id':run_id}))
        if mode == 'crash_after_node':
            original = svc.record
            def record(*args):
                original(*args)
                if args[2:4] == ('triage','completed'):
                    os._exit(17)
            svc.record = record
        job = await svc.drive(run_id)
    else:
        run_id = json.loads(Path(output).read_text())['run_id']
        job = await svc.inspect(run_id)
        if mode == 'crash_approval_receipt':
            original = svc.accepted
            def accepted(*args):
                value = original(*args)
                if value is not None: os._exit(17)
                return value
            svc.accepted = accepted
        elif mode == 'crash_approval_node':
            original = svc.record
            def record(*args):
                original(*args)
                if args[2:4] == ('human_approval','completed'): os._exit(17)
            svc.record = record
        if mode in ('approve','crash_approval_receipt','crash_approval_node'):
            job = await svc.drive(run_id, approval={**job['pending_approval']['token'],'decision':'approve'})
        elif mode == 'recover':
            job = await svc.drive(run_id)
        elif mode == 'uncertain':
            try:
                await svc.drive(run_id)
            except ValueError as e:
                job['resume_error'] = str(e)
    Path(output).write_text(json.dumps(job))


asyncio.run(main())
