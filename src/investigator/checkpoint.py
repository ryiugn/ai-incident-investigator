"""Local SQLite persistence and single-writer execution coordination."""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from . import checkpoint_state as data
from .budgets import Limits, UnknownOutcome
from .telemetry import Telemetry
from .evidence import canonical


@contextmanager
def writer_lock(path):
    """Nonblocking OS lock; unlike a TTL lease it cannot expire under a live worker."""
    handle = open(str(path) + '.lock', 'a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ValueError('Investigation store busy; another execution is active.') from error
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError('Investigation store busy; another execution is active.') from error
        yield
    finally:
        handle.close()


class Investigations:
    def __init__(self, path, provider, adapter_factory=Telemetry):
        self.path, self.provider, self.adapter_factory = Path(path), provider, adapter_factory
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS investigation_meta (version INTEGER NOT NULL)')
            version = db.execute('SELECT version FROM investigation_meta').fetchone()
            if version is None:
                db.execute('INSERT INTO investigation_meta VALUES (1)')
            elif version[0] != 1:
                raise ValueError('Unsupported checkpoint store version.')
            db.execute('CREATE TABLE IF NOT EXISTS investigations (id TEXT PRIMARY KEY, state TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS execution_journal (run_id TEXT, revision INTEGER, node TEXT, status TEXT, state TEXT, PRIMARY KEY(run_id,revision,node))')
            db.execute('CREATE TABLE IF NOT EXISTS approvals (run_id TEXT, approval_id TEXT, payload TEXT NOT NULL, PRIMARY KEY(run_id,approval_id))')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=3)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def ids(self):
        with self.db() as db:
            return [r[0] for r in db.execute('SELECT id FROM investigations')]

    def load(self, run_id):
        with self.db() as db:
            row = db.execute('SELECT state FROM investigations WHERE id=?',(run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        state = json.loads(row[0])
        data.validate(state)
        return state

    def create(self, case, case_id='local', limits=None, run_id=None):
        if self.provider.paid and hasattr(self.provider,'ledger_path') and not self.provider.ledger_path:
            raise ValueError('Durable paid runs require a persistent spending ledger.')
        run_id = run_id or uuid.uuid4().hex
        state = data.initial(case, self.provider, limits or Limits(), self.adapter_factory, run_id, case_id)
        with self.db() as db:
            db.execute('INSERT INTO investigations VALUES (?,?)',(run_id, canonical(state)))
        return run_id

    def journal(self, run_id, revision, node):
        with self.db() as db:
            row = db.execute('SELECT status,state FROM execution_journal WHERE run_id=? AND revision=? AND node=?',
                             (run_id,revision,node)).fetchone()
        return (row[0],json.loads(row[1])) if row else None

    def record(self, run_id, revision, node, status, state):
        # Journal and inspectable projection advance atomically. Graph checkpoint is
        # a separate write: a replay bridges that gap using this completed output.
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO execution_journal VALUES (?,?,?,?,?)',
                       (run_id,revision,node,status,canonical(state)))
            db.execute('UPDATE investigations SET state=? WHERE id=?',(canonical(state),run_id))

    def uncertain(self, run_id):
        with self.db() as db:
            return db.execute("SELECT 1 FROM execution_journal WHERE run_id=? AND status='dispatching' LIMIT 1",(run_id,)).fetchone() is not None

    @asynccontextmanager
    async def graph(self):
        from .durable_graph import build_durable_graph
        async with AsyncSqliteSaver.from_conn_string(str(self.path)) as saver:
            await saver.conn.execute('PRAGMA synchronous=FULL')
            yield build_durable_graph(self, saver)

    @staticmethod
    def config(run_id):
        return {'configurable':{'thread_id':run_id},'recursion_limit':64}

    def accepted(self, run_id, pending):
        if not pending:
            return None
        with self.db() as db:
            row = db.execute('SELECT payload FROM approvals WHERE run_id=? AND approval_id=?',
                             (run_id,pending['approval_id'])).fetchone()
        return json.loads(row[0]) if row else None

    async def inspect(self, run_id, active=None):
        state = self.load(run_id)
        async with self.graph() as graph:
            snapshot = await graph.aget_state(self.config(run_id))
        pending = state['pending']
        accepted = self.accepted(run_id,pending)
        interrupted = any(t.interrupts for t in snapshot.tasks)
        if active is None:
            try:
                with writer_lock(self.path): pass
                active = False
            except ValueError:
                active = True
        status, resumable, message, approval = 'interrupted', True, 'Resume from the last durable boundary.', None
        if self.uncertain(run_id):
            resumable = False
            message = 'A dispatched call has an unknown outcome. Reservations are retained. Start a new investigation; this call will not be repeated.'
        elif state['route'] == 'end':
            status, resumable, message = 'finished', False, ''
        elif interrupted and pending and not accepted:
            status = 'awaiting_approval'
            approval = {**pending, 'token':dict(approval_id=pending['approval_id'],
                         revision=state['revision'],checkpoint_id=snapshot.config['configurable']['checkpoint_id'])}
            message = 'Review the exact query to continue. Waiting does not consume active execution time.'
        if active and status == 'interrupted':
            status, message = 'running', 'Investigation is executing.'
        return dict(run_id=run_id, case_id=state['case_id'], workflow='adaptive', state=status,
                    resumable=resumable, recovery_message=message, pending_approval=approval, result=data.result(state),
                    **({'created_at':state['created_at']} if 'created_at' in state else {}))

    async def drive(self, run_id, approval=None):
        with writer_lock(self.path):
            state = self.load(run_id)
            data.restore(state,self.provider,self.adapter_factory)  # validate before accepting approval
            if self.uncertain(run_id):
                raise ValueError('Unknown external-call outcome; start a new investigation. Reservations retained.')
            job = await self.inspect(run_id, active=False)
            if state['route'] == 'end':
                raise ValueError('Investigation already finished; stale approval or resume.')
            if approval is not None:
                expected = job['pending_approval']
                if (not expected or set(approval) != {'approval_id','revision','checkpoint_id','decision'}
                        or approval['decision'] not in ('approve','decline')
                        or any(approval[k] != v for k,v in expected['token'].items())):
                    raise ValueError('Invalid or stale approval; reload the pending query.')
                with self.db() as db:
                    db.execute('INSERT INTO approvals VALUES (?,?,?)',(run_id,approval['approval_id'],canonical(approval)))
            accepted = self.accepted(run_id,state['pending'])
            async with self.graph() as graph:
                config = self.config(run_id)
                checkpoint = await graph.aget_state(config)
                value = None if checkpoint.values else {'investigation':state}
                if any(t.interrupts for t in checkpoint.tasks):
                    # The application journal may already contain approval-node
                    # output (pending cleared) while LangGraph still has the old
                    # interrupt. Resolve the receipt against that graph revision.
                    accepted = self.accepted(run_id,checkpoint.values['investigation']['pending'])
                    if accepted is None:
                        return job
                    value = Command(resume=accepted)
                try:
                    await graph.ainvoke(value, config=config, durability='sync')
                except UnknownOutcome:
                    pass  # Keep the pre-dispatch journal and conservative reservation.
            return await self.inspect(run_id, active=False)
