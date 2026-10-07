"""Explicit OTel SDK instrumentation with a bounded, sanitized local processor.

No global provider, auto-instrumentation, network exporter, SQL, exception text,
attributes, events, baggage, or resource metadata enters the public recorder.
"""
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

OPERATIONS = {'orders.request', 'database.acquire', 'database.query', 'shipping.request', 'shipping.quote'}


def iso(ns):
    return datetime.fromtimestamp(ns / 1_000_000_000, timezone.utc).isoformat()


class Recorder(SpanProcessor):
    def __init__(self, service, capacity):
        self.service, self.rows, self.complete = service, deque(maxlen=capacity), True
        self.lock = Lock()
        self.active = 0
        self.started_at = datetime.now(timezone.utc).isoformat()

    def on_start(self, span, parent_context=None):
        with self.lock:
            self.active += 1

    def on_end(self, span):
        context = span.context
        row = dict(source_record_id=f'{context.trace_id:032x}-{context.span_id:016x}',
            trace_id=f'{context.trace_id:032x}', span_id=f'{context.span_id:016x}',
            parent_span_id=f'{span.parent.span_id:016x}' if span.parent else None,
            service=self.service, operation=span.name, start_time=iso(span.start_time),
            end_time=iso(span.end_time), status=span.status.status_code.name.lower())
        with self.lock:
            self.active -= 1
            if len(self.rows) == self.rows.maxlen: self.complete = False
            self.rows.append(row)

    def snapshot(self):
        with self.lock:
            return {'spans':[dict(row) for row in self.rows], 'complete':self.complete and self.active == 0, 'started_at':self.started_at}


class LocalTracing:
    def __init__(self, service, capacity=10000):
        if service not in {'orders','shipping'} or not 1 <= capacity <= 10000:
            raise ValueError('invalid recorder configuration')
        self.recorder = Recorder(service, capacity)
        self.provider = TracerProvider(sampler=ALWAYS_ON)
        self.provider.add_span_processor(self.recorder)
        self.tracer = self.provider.get_tracer('local-investigation-environment')
        self.propagator = TraceContextTextMapPropagator()

    @contextmanager
    def span(self, operation, headers=None):
        if operation not in OPERATIONS: raise ValueError('operation not allowed')
        context = self.propagator.extract(headers) if headers is not None else None
        with self.tracer.start_as_current_span(operation, context=context,
                record_exception=False, set_status_on_exception=False) as span:
            try:
                yield span
            except BaseException:
                span.set_status(Status(StatusCode.ERROR))
                raise
            else:
                span.set_status(Status(StatusCode.OK))

    def headers(self):
        carrier = {}
        self.propagator.inject(carrier)
        return carrier

    def snapshot(self):
        return self.recorder.snapshot()


def freeze_traces(recordings, window):
    """Freeze completed spans wholly inside the horizon; excluded overlaps are missing."""
    parse=lambda value: datetime.fromisoformat(value.replace('Z','+00:00'))
    start,end=parse(window['start']),parse(window['end'])
    complete=all(r.get('complete') is True for r in recordings) and len(recordings)==2
    spans=[]
    for recording in recordings:
        if recording.get('started_at') and parse(recording['started_at'])>start:
            complete=False
        for row in recording.get('spans',[]):
            a,b=parse(row['start_time']),parse(row['end_time'])
            if start<=a and b<=end and a<end:
                spans.append(dict(row))
            elif a<=end and b>=start:
                complete=False
    spans.sort(key=lambda r:(parse(r['start_time']),r['source_record_id']))
    identities={(s['trace_id'],s['span_id']) for s in spans}
    if any(s.get('parent_span_id') and (s['trace_id'],s['parent_span_id']) not in identities for s in spans):
        complete=False
    if len(spans)>10000:
        spans=spans[:10000];complete=False
    return {'traces':spans,'traces_complete':complete}
