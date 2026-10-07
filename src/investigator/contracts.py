from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, model_validator, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)


class Window(Contract):
    start: AwareDatetime
    end: AwareDatetime

    @field_validator('start', 'end')
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def ordered(self):
        if not 0 < (self.end - self.start).total_seconds() <= 1800:
            raise ValueError('window must be positive and at most 30 minutes')
        return self


class Alert(Contract):
    alert_id: str = Field(min_length=1, max_length=80)
    service: Literal['orders'] = 'orders'
    triggered_at: AwareDatetime
    window: Window
    symptom: str = Field(min_length=1, max_length=300)


METRICS = ('request_count', 'error_count', 'request_latency_p95', 'db_pool_capacity',
           'db_pool_in_use', 'db_pool_acquire_timeout_count', 'db_query_duration_p95',
           'db_lock_wait_count', 'dependency_duration_p95', 'dependency_timeout_count',
           'dependency_error_count')
EVENTS = ('dependency_timeout', 'dependency_error', 'db_timeout', 'request_failed',
          'request_ok', 'auth_warning', 'db_query', 'pool_timeout')


class LogArgs(Contract):
    service: Literal['orders']
    window: Window
    levels: list[Literal['info', 'warning', 'error']] | None = None
    event_codes: list[str] | None = None
    request_id: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=30, ge=1, le=100, strict=True)

    @field_validator('event_codes')
    @classmethod
    def codes(cls, value):
        if value is not None and (len(value) > len(EVENTS) or not set(value) <= set(EVENTS)):
            raise ValueError('event code not allowed')
        return value


class MetricArgs(Contract):
    service: Literal['orders']
    window: Window
    metric_names: list[str] = Field(min_length=1, max_length=4)
    step_seconds: Literal[10, 30, 60] = 30

    @field_validator('metric_names')
    @classmethod
    def names(cls, value):
        if not set(value) <= set(METRICS):
            raise ValueError('metric not allowed')
        return sorted(set(value))


class ChangeArgs(Contract):
    service: Literal['orders']
    window: Window
    limit: int = Field(default=5, ge=1, le=10, strict=True)


class RunbookArgs(Contract):
    query: str = Field(min_length=1, max_length=300)
    service: Literal['orders'] = 'orders'
    limit: int = Field(default=2, ge=1, le=3, strict=True)


class TraceArgs(Contract):
    service: Literal['orders', 'shipping']
    window: Window
    trace_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    limit: int = Field(default=30, ge=1, le=100, strict=True)

    @field_validator('trace_id')
    @classmethod
    def nonzero(cls, value):
        if value is not None and int(value, 16) == 0:
            raise ValueError('invalid trace identifier')
        return value


TOOL_SCHEMAS = dict(query_traces=TraceArgs, query_logs=LogArgs, query_metrics=MetricArgs,
                    get_changes=ChangeArgs, search_runbooks=RunbookArgs)


class ToolRequest(Contract):
    tool: str = Field(max_length=40)
    arguments: dict


class Hypothesis(Contract):
    """A concise public candidate assessment, never a reasoning transcript."""
    hypothesis_id: str = Field(min_length=1, max_length=60, pattern=r'^[a-zA-Z0-9_-]+$')
    candidate: str = Field(min_length=1, max_length=240)
    supporting_ids: list[str] = Field(default_factory=list, max_length=8)
    contradicting_ids: list[str] = Field(default_factory=list, max_length=8)
    status: Literal['open', 'supported', 'weakened', 'rejected']
    uncertainty: str = Field(min_length=1, max_length=300)
    next_check: str = Field(min_length=1, max_length=300)


class Decision(Contract):
    action: Literal['collect', 'report', 'insufficient', 'escalate']
    tool_request: ToolRequest | None = None
    summary: str = Field(max_length=400)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=4)

    @model_validator(mode='after')
    def consistent(self):
        if (self.action == 'collect') != (self.tool_request is not None):
            raise ValueError('collect requires exactly one tool request')
        if len({h.hypothesis_id for h in self.hypotheses}) != len(self.hypotheses):
            raise ValueError('hypothesis identifiers must be unique within a decision')
        return self


class Claim(Contract):
    claim_id: str = Field(max_length=80)
    text: str = Field(min_length=1, max_length=1200)
    type: Literal['observation', 'inference']
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    limitations: str = Field(default='', max_length=600)


class Alternative(Contract):
    description: str = Field(max_length=600)
    supporting_ids: list[str] = Field(default_factory=list, max_length=20)
    contradicting_ids: list[str] = Field(default_factory=list, max_length=20)
    unresolved_reason: str = Field(max_length=600)


class NextStep(Contract):
    action: str = Field(max_length=600)
    purpose: str = Field(max_length=600)
    prerequisite: str = Field(default='', max_length=400)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class Report(Contract):
    status: Literal['diagnosis', 'insufficient_evidence', 'error']
    observed_symptoms: list[Claim] = Field(default_factory=list, max_length=15)
    likely_cause: Claim | None = None
    diagnostic_level: Literal['condition', 'root_cause', 'undetermined']
    alternatives: list[Alternative] = Field(default_factory=list, max_length=8)
    missing_evidence: list[str] = Field(default_factory=list, max_length=12)
    uncertainty: str = Field(max_length=1000)
    next_steps: list[NextStep] = Field(default_factory=list, max_length=8)
    requires_human: bool = True

    @model_validator(mode='after')
    def consistency(self):
        if self.status == 'diagnosis':
            if self.likely_cause is None or self.diagnostic_level == 'undetermined':
                raise ValueError('diagnosis requires a cited cause and diagnostic level')
        elif self.likely_cause is not None or self.diagnostic_level != 'undetermined':
            raise ValueError('non-diagnosis cannot assert a cause')
        return self
