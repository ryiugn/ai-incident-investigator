import asyncio
from fastapi import FastAPI, Request
from .tracing import LocalTracing
from pydantic import BaseModel, Field, ConfigDict

app = FastAPI()
delay_ms = 0
tracing = LocalTracing('shipping')


class Control(BaseModel):
    model_config = ConfigDict(extra='forbid')
    delay_ms: int = Field(ge=0, le=2000)


@app.get('/health')
async def health():
    return {'ready':True}


@app.get('/quote')
async def quote(request: Request):
    with tracing.span('shipping.quote',headers=dict(request.headers)):
        await asyncio.sleep(delay_ms / 1000)
        return {'price_cents':500}


@app.get('/traces')
async def traces():
    return tracing.snapshot()


@app.post('/control')
async def control(config: Control):
    global delay_ms
    delay_ms = config.delay_ms
    return {'ready':True}
