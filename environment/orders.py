import asyncio
import os
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import httpx
import psycopg
from psycopg_pool import AsyncConnectionPool, PoolTimeout
from fastapi import FastAPI, HTTPException, Request
from .tracing import LocalTracing
from pydantic import BaseModel, ConfigDict, Field

DATABASE_URL = os.environ['DATABASE_URL']
pool = AsyncConnectionPool(DATABASE_URL, min_size=4, max_size=4, open=False,
                           kwargs={'autocommit':True, 'options':'-c statement_timeout=600'})
records = {k:deque(maxlen=20000) for k in ('logs','metrics','changes')}
config = {'dependency_path':'/quote'}
held = []
tracing = LocalTracing('orders')


def now():
    return datetime.now(timezone.utc).isoformat()


def record(kind, **fields):
    item = dict(source_record_id=uuid.uuid4().hex, timestamp=now(), service='orders', **fields)
    records[kind].append(item)


def metric(name, value, unit='count'):
    record('metrics', metric=name, value=value, unit=unit)


async def sampler():
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        while True:
            stats = pool.get_stats()
            metric('db_pool_capacity', 4)
            metric('db_pool_in_use', stats.get('pool_size', 4) - stats.get('pool_available', 0))
            cursor = await conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'")
            metric('db_lock_wait_count', (await cursor.fetchone())[0])
            await asyncio.sleep(.1)


@asynccontextmanager
async def lifespan(app):
    await pool.open(); await pool.wait()
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        await conn.execute('CREATE TABLE IF NOT EXISTS inventory (id int PRIMARY KEY, sku text, payload text, stock int)')
        await conn.execute("INSERT INTO inventory SELECT n, 'item-'||n, repeat('x',200), 100 FROM generate_series(1,300000) n ON CONFLICT DO NOTHING")
        await conn.execute('CREATE INDEX IF NOT EXISTS inventory_sku_idx ON inventory(sku)')
        await conn.execute('ANALYZE inventory')
    task = asyncio.create_task(sampler())
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass
    for conn in held: await pool.putconn(conn)
    await pool.close()


app = FastAPI(lifespan=lifespan)


@app.get('/health')
async def health():
    return {'ready':True}


@app.get('/clock')
async def clock():
    return {'timestamp':now()}


@app.get('/traces')
async def traces():
    return tracing.snapshot()


@asynccontextmanager
async def traced_connection():
    with tracing.span('database.acquire'):
        conn = await pool.getconn(timeout=.35)
    try:
        yield conn
    finally:
        await pool.putconn(conn)


@app.post('/orders')
async def order(request: Request, sku: int = 299999):
    with tracing.span('orders.request', headers=dict(request.headers)):
        return await process_order(sku)


async def process_order(sku):
    if not 1 <= sku <= 300000: raise HTTPException(400, 'invalid item')
    begin = time.monotonic()
    event, message, failed = 'request_ok', 'Order request completed', False
    query_start = None
    metric('request_count', 1)
    try:
        async with traced_connection() as conn:
            query_start = time.monotonic()
            with tracing.span('database.query'):
                for _ in range(5):
                    await conn.execute('SELECT length(payload) FROM inventory WHERE sku=%s', (f'item-{sku}',))
                await conn.execute('UPDATE inventory SET stock=stock WHERE id=1')
            metric('db_query_duration_p95', (time.monotonic()-query_start)*1000, 'ms')
            query_start = None
        dep_start = time.monotonic()
        try:
            with tracing.span('shipping.request'):
                async with httpx.AsyncClient(timeout=.5) as client:
                    response = await client.get(os.environ['SHIPPING_URL'] + config['dependency_path'], headers=tracing.headers())
                    response.raise_for_status()
        finally:
            metric('dependency_duration_p95', (time.monotonic()-dep_start)*1000, 'ms')
    except PoolTimeout:
        event, message, failed = 'pool_timeout', 'Database connection acquisition exceeded deadline', True
        metric('db_pool_acquire_timeout_count', 1)
    except psycopg.errors.QueryCanceled:
        event, message, failed = 'db_timeout', 'Database statement exceeded deadline', True
    except httpx.TimeoutException:
        event, message, failed = 'dependency_timeout', 'Shipping request exceeded deadline', True
        metric('dependency_timeout_count', 1)
    except httpx.HTTPStatusError as error:
        event, message, failed = 'dependency_error', f'Shipping returned HTTP {error.response.status_code}', True
        metric('dependency_error_count', 1)
    finally:
        if query_start is not None:
            metric('db_query_duration_p95', (time.monotonic()-query_start)*1000, 'ms')
        metric('request_latency_p95', (time.monotonic()-begin)*1000, 'ms')
        metric('error_count', int(failed))
        record('logs', level='error' if failed else 'info', event_code=event, message=message,
               fields={'dependency_path':config['dependency_path']})
    if failed: raise HTTPException(503, 'Order temporarily unavailable')
    return {'accepted':True}


class Control(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dependency_path: str = Field(default='/quote', pattern=r'^/(quote|quotes-invalid)$')
    hold_connections: bool = False


@app.post('/control')
async def control(value: Control):
    for conn in held: await pool.putconn(conn)
    held.clear()
    if value.dependency_path != config['dependency_path']:
        record('changes', revision=uuid.uuid4().hex, changed={'dependency_path':{'old':config['dependency_path'],'new':value.dependency_path}}, rollout_scope='orders')
    config['dependency_path'] = value.dependency_path
    if value.hold_connections:
        try:
            for _ in range(4): held.append(await pool.getconn(timeout=2))
        except Exception:
            for conn in held: await pool.putconn(conn)
            held.clear()
            raise
    return {'ready':True, 'held':len(held)}


@app.get('/telemetry')
async def telemetry():
    return {kind:list(items) for kind,items in records.items()}
