import time
from pydantic import Field
from .contracts import Contract


class Limits(Contract):
    tool_dispatches: int = Field(default=8, ge=0, le=8)
    model_requests: int = Field(default=10, ge=0, le=10)
    input_tokens: int = Field(default=30000, ge=0, le=30000)
    output_tokens: int = Field(default=5000, ge=0, le=5000)
    seconds: float = Field(default=90, gt=0, le=90)
    tool_seconds: float = Field(default=3, gt=0, le=3)
    provider_seconds: float = Field(default=20, gt=0, le=20)


class Exhausted(Exception):
    pass


class UnknownOutcome(RuntimeError):
    """A durable dispatch may have executed; never retry it automatically."""


class Budget:
    def __init__(self, limits):
        self.limits = limits
        self.start = time.monotonic()
        self.usage = dict(model_requests=0, tool_dispatches=0, logical_queries=0, tool_retries=0,
            cache_hits=0, input_tokens=0, output_tokens=0, cache_tokens=0, repairs=0,
            estimated_cost_usd=0.0, unknown_usage_reservations=[], elapsed_ms=0)

    def remaining(self):
        return max(0, self.limits.seconds - (time.monotonic() - self.start))

    def check_time(self):
        if self.remaining() <= .001:
            raise Exhausted('deadline')

    def tool(self, retry=False):
        self.check_time()
        if self.usage['tool_dispatches'] >= self.limits.tool_dispatches:
            raise Exhausted('tool_budget')
        self.usage['tool_dispatches'] += 1
        self.usage['tool_retries'] += int(retry)

    def model(self, input_bound, final=False):
        self.check_time()
        reserve_calls, reserve_tokens = (0, 0) if final else (1, 1000)
        unknown = self.usage['unknown_usage_reservations']
        pending_input = sum(r['input_tokens'] for r in unknown)
        pending_output = sum(r['output_tokens'] for r in unknown)
        if self.usage['model_requests'] >= self.limits.model_requests - reserve_calls:
            raise Exhausted('model_budget')
        if self.usage['input_tokens'] + pending_input + input_bound > self.limits.input_tokens:
            raise Exhausted('input_budget')
        available = self.limits.output_tokens - self.usage['output_tokens'] - pending_output - reserve_tokens
        if available < 200:
            raise Exhausted('output_budget')
        self.usage['model_requests'] += 1
        return min(1000, available)

    def finish(self):
        self.usage['elapsed_ms'] = round((time.monotonic() - self.start) * 1000)
        return self.usage
