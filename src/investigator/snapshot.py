from pydantic import Field, AwareDatetime, field_validator, model_validator
from typing import Literal
from datetime import timezone
from .contracts import Contract, Window, METRICS, EVENTS


class Record(Contract):
    source_record_id: str = Field(min_length=1,max_length=100)
    timestamp: AwareDatetime
    service: Literal['orders']


class Log(Record):
    level: Literal['info','warning','error']
    event_code: str
    message: str = Field(max_length=2000)
    request_id: str | None = None
    fields: dict = Field(default_factory=dict)

    @field_validator('fields')
    @classmethod
    def approved(cls,value):
        if not set(value)<={'timeout_ms','dependency_path','http_status','query_fingerprint'}:
            raise ValueError('unapproved structured log fields')
        if any(not isinstance(v,(str,int,float,bool,type(None))) for v in value.values()):
            raise ValueError('nested fields not supported')
        return value

    @field_validator('event_code')
    @classmethod
    def event(cls,value):
        if value not in EVENTS: raise ValueError('unapproved event code')
        return value


class Metric(Record):
    metric: str
    value: float = Field(ge=0)
    unit: Literal['count','ms']

    @field_validator('metric')
    @classmethod
    def name(cls,value):
        if value not in METRICS: raise ValueError('unapproved metric')
        return value


class Change(Record):
    revision: str = Field(max_length=100)
    changed: dict
    rollout_scope: Literal['orders']

    @field_validator('changed')
    @classmethod
    def sanitized(cls,value):
        if not set(value)<={'dependency_path'}: raise ValueError('unapproved configuration keys')
        for change in value.values():
            if set(change)!={'old','new'} or any(not isinstance(v,str) or len(v)>200 for v in change.values()):
                raise ValueError('invalid sanitized change')
        return value


class Runbook(Contract):
    source_record_id: str = Field(max_length=100)
    document_id: str = Field(max_length=100)
    version: str = Field(max_length=40)
    section: str = Field(max_length=100)
    text: str = Field(max_length=4000)


class TraceSpan(Contract):
    source_record_id: str = Field(min_length=1, max_length=100)
    trace_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    span_id: str = Field(pattern=r'^[0-9a-f]{16}$')
    parent_span_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{16}$')
    service: Literal['orders', 'shipping']
    start_time: AwareDatetime
    end_time: AwareDatetime
    operation: Literal['orders.request', 'database.acquire', 'database.query', 'shipping.request', 'shipping.quote']
    status: Literal['ok', 'error', 'unset']

    @field_validator('trace_id', 'span_id', 'parent_span_id')
    @classmethod
    def nonzero(cls, value):
        if value is not None and int(value, 16) == 0: raise ValueError('invalid span identifier')
        return value

    @field_validator('start_time', 'end_time')
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def ordered(self):
        if self.end_time < self.start_time: raise ValueError('negative span duration')
        if self.parent_span_id == self.span_id: raise ValueError('span cannot parent itself')
        return self


class Snapshot(Contract):
    snapshot_id: str = Field(min_length=1,max_length=100)
    window: Window
    complete: bool
    logs: list[Log] = Field(max_length=10000)
    metrics: list[Metric] = Field(max_length=20000)
    changes: list[Change] = Field(max_length=100)
    runbooks: list[Runbook] = Field(max_length=20)

    traces: list[TraceSpan] | None = Field(default=None, max_length=10000)
    traces_complete: bool | None = None

    @model_validator(mode='after')
    def unique(self):
        for records in (self.logs,self.metrics,self.changes,self.runbooks,self.traces or []):
            ids=[r.source_record_id for r in records]
            if len(set(ids))!=len(ids): raise ValueError('duplicate source record identifiers')
        spans=self.traces or []
        if len({(s.trace_id,s.span_id) for s in spans})!=len(spans):
            raise ValueError('duplicate trace span identity')
        if any(not (self.window.start<=s.start_time<self.window.end and s.end_time<=self.window.end) for s in spans):
            raise ValueError('trace span outside snapshot horizon')
        return self
