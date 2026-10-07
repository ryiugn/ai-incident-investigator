import asyncio
import uuid
from .contracts import Alert, Report, Decision, TOOL_SCHEMAS
from .telemetry import Telemetry
from .baseline import schedule
from .evidence import validate_citations, canonical, digest
from .archive import save_run
from .budgets import Budget, Limits, Exhausted, UnknownOutcome


class RunContext:
    def __init__(self, case, provider, limits, adapter_factory):
        self.alert = Alert.model_validate(case['alert'])
        self.telemetry = adapter_factory(case['telemetry_snapshot'])
        if not self.telemetry.window.start <= self.alert.window.start < self.alert.window.end <= self.telemetry.window.end:
            raise ValueError('alert outside snapshot')
        self.provider, self.budget = provider, Budget(limits)
        self.run_id = uuid.uuid4().hex
        self.events, self.nodes, self.prompts = [], [], []
        self.supplied, self.cache = set(), {}
        self.no_progress, self.reason = 0, 'report'
        self.decision, self.report = None, None
        self.hypotheses, self.hypothesis_history = [], []
        self.before_dispatch = None

    def payload(self, contract):
        # Only explicit public fields cross the model boundary; no filenames/private metadata.
        evidence, used = [], 0
        registered = list(self.telemetry.registry.export().values())
        for item in registered:
            # Full lineage stays immutable in the registry. Repeated source-ID arrays
            # add no diagnostic observation and can crowd out later metrics.
            excerpt = {key:item[key] for key in ('evidence_id','snapshot_id','content_hash','source_kind','payload','coverage')}
            size = len(canonical(excerpt))
            if used + size <= 16000:
                evidence.append(excerpt); used += size
        events = []
        for event in self.events[-16:]:
            metadata = {k:v for k,v in event.items() if k in ('tool','status','error','duplicate','summary','arguments','validation_reason')}
            metadata.update({k:v for k,v in event.get('result',{}).items() if k in ('coverage','truncated','total_matches')})
            events.append(metadata)
        payload = dict(alert=self.alert.model_dump(mode='json'), query_window=self.telemetry.window.model_dump(mode='json'), evidence=evidence, tool_events=events,
                       evidence_selection={'available_count':len(registered),'supplied_count':len(evidence),
                                           'omitted_count':len(registered)-len(evidence), 'policy':'collection order; 16000 character cap'})
        if contract is Decision:
            payload['allowed_tools'] = {name:schema.model_json_schema() for name,schema in TOOL_SCHEMAS.items()}
        # Compact public candidate continuity; historical citations are deliberately
        # excluded because each new update may cite only this request's evidence.
        if self.hypotheses:
            payload['previous_hypotheses'] = [
                {k:h[k] for k in ('hypothesis_id','candidate','status')}
                for h in self.hypotheses[-4:]]
        return payload

    async def model(self, contract, final=False):
        validation_feedback = None
        for repair in range(2):
            payload = self.payload(contract)
            if repair:
                payload['repair'] = {'instruction':'Correct these validation errors; cite only supplied IDs.', 'errors':validation_feedback}
            estimate = getattr(self.provider, 'estimate_input', lambda p,c: len(canonical(p).encode()) + len(canonical(c.model_json_schema()).encode()) + 1024)(payload, contract)
            max_tokens = self.budget.model(estimate, final)
            request_number = self.budget.usage['model_requests']
            supplied = {e['evidence_id'] for e in payload['evidence']}
            self.supplied.update(supplied)
            self.prompts.append(dict(request=request_number, contract=contract.__name__, payload=payload,
                                     input_bound=estimate, max_output_tokens=max_tokens))
            reservation = dict(request=request_number, input_tokens=estimate, output_tokens=max_tokens,
                               reserved_cost_usd=(estimate+5*max_tokens)/1e6 if self.provider.paid else 0.0)
            timeout = min(self.budget.remaining(), self.budget.limits.provider_seconds)
            if self.before_dispatch:
                self.budget.usage['unknown_usage_reservations'].append(reservation)
                self.before_dispatch('model', timeout)
            try:
                raw, tokens = await asyncio.wait_for(self.provider.respond(payload, contract, max_tokens, timeout), timeout)
            except (Exception, asyncio.CancelledError) as error:
                if self.provider.paid and not self.before_dispatch:
                    self.budget.usage['unknown_usage_reservations'].append(reservation)
                if isinstance(error, asyncio.CancelledError):
                    raise
                if self.before_dispatch:
                    raise UnknownOutcome('Provider dispatch outcome is uncertain.') from error
                raise Exhausted('provider_timeout' if isinstance(error, TimeoutError) else 'provider_error') from error
            if self.before_dispatch:
                self.budget.usage['unknown_usage_reservations'].remove(reservation)
            for key in ('input_tokens','output_tokens','cache_tokens'):
                self.budget.usage[key] += tokens[key]
            if self.provider.paid:
                self.budget.usage['estimated_cost_usd'] += (tokens['input_tokens']+5*tokens['output_tokens']+1.25*tokens['cache_tokens'])/1e6
            if self.budget.usage['input_tokens'] > self.budget.limits.input_tokens or self.budget.usage['output_tokens'] > self.budget.limits.output_tokens:
                raise Exhausted('provider_usage_overrun')
            self.budget.check_time()
            try:
                value = contract.model_validate(raw)
                if contract in (Report, Decision):
                    validate_citations(value.model_dump(), self.telemetry.registry.export(), supplied)
                if contract is Decision and value.hypotheses:
                    updates = [h.model_dump(mode='json') for h in value.hypotheses]
                    latest = {h['hypothesis_id']:h for h in self.hypotheses}
                    latest.update({h['hypothesis_id']:h for h in updates})
                    self.hypotheses = list(latest.values())
                    self.hypothesis_history.append(dict(request=request_number, hypotheses=updates))
                return value
            except ValueError as error:
                validation_feedback = [{'field':'.'.join(map(str,e['loc'])), 'reason':e['msg']} for e in error.errors(include_input=False)][:8] if hasattr(error,'errors') else [{'reason':'Citation validation failed; use only supplied IDs.'}]
                if self.budget.usage['repairs'] >= 1:
                    raise Exhausted('invalid_output')
                self.budget.usage['repairs'] += 1
        raise Exhausted('invalid_output')

    async def dispatch(self, request):
        self.budget.usage['logical_queries'] += 1
        before = set(self.telemetry.registry.export())
        try:
            args = self.telemetry.validate(request)
        except ValueError as error:
            reason=str(error) if str(error) in ('out_of_scope','tool not allowed') else 'schema_mismatch'
            self.events.append(dict(tool=request.tool, status='error', error='invalid_arguments', validation_reason=reason, arguments=request.arguments))
            self.no_progress += 1
            return
        key = digest(dict(snapshot=self.telemetry.snapshot['snapshot_id'], tool=request.tool, arguments=args.model_dump(mode='json')))
        if key in self.cache:
            self.budget.usage['cache_hits'] += 1
            self.events.append(dict(tool=request.tool, status=self.cache[key]['status'], duplicate=True, result=self.cache[key]))
            self.no_progress += 1
            return
        for retry in range(2):
            self.budget.tool(bool(retry))
            timeout = min(self.budget.remaining(), self.budget.limits.tool_seconds)
            if self.before_dispatch:
                self.before_dispatch('tool', timeout)
            try:
                result = await asyncio.wait_for(self.telemetry.query(request), timeout)
                self.cache[key] = result
                self.events.append(dict(tool=request.tool, arguments=args.model_dump(mode='json'), status=result['status'], result=result))
                self.no_progress = 0 if set(self.telemetry.registry.export()) - before else self.no_progress + 1
                return
            except (TimeoutError, ConnectionError) as error:
                if self.before_dispatch:
                    raise UnknownOutcome('Tool dispatch outcome is uncertain.') from error
                self.events.append(dict(tool=request.tool, status='error', error='timeout_or_unavailable', retry=bool(retry)))
        self.no_progress += 1

    async def finalize(self):
        self.nodes.append('finalize')
        try:
            self.report = await self.model(Report, final=True)
        except Exhausted as error:
            if self.reason == 'report':
                self.reason = str(error)
            self.fallback()

    def fallback(self):
        self.report = Report(status='error', diagnostic_level='undetermined',
            missing_evidence=['Validated final assessment unavailable; inspect the collected evidence and tool events.'],
            uncertainty=f'Operational partial outcome: {self.reason}. No new diagnosis is asserted.')


async def run_investigation(case, provider, archive=None, minimal=False, workflow='fixed', limits=None, adapter_factory=Telemetry):
    if workflow not in ('fixed', 'adaptive'):
        raise ValueError('unknown workflow')
    ctx = RunContext(case, provider, limits or Limits(), adapter_factory)
    try:
        if workflow == 'adaptive':
            from .graph import build_graph
            await build_graph(ctx).ainvoke({'route':'triage'}, config={'recursion_limit':64})
        else:
            try:
                for request in schedule(ctx.alert, minimal, ctx.telemetry.window):
                    await ctx.dispatch(request)
            except Exhausted as error:
                ctx.reason = str(error)
            await ctx.finalize()
    except asyncio.CancelledError:
        ctx.reason = 'cancelled'; ctx.fallback()
    except Exception:
        ctx.reason = 'internal_error'; ctx.fallback()
    result = dict(run_id=ctx.run_id, workflow=workflow, provider=provider.name,
        report=ctx.report.model_dump(mode='json'), termination_reason=ctx.reason,
        evidence=ctx.telemetry.registry.export(), events=ctx.events, nodes=ctx.nodes,
        usage=ctx.budget.finish(), prompts=ctx.prompts, limits=ctx.budget.limits.model_dump(),
        snapshot_hash=digest(case['telemetry_snapshot']), schema_version=1)
    result.update(hypotheses=ctx.hypotheses, hypothesis_history=ctx.hypothesis_history)
    from .reproducibility import configuration, metadata
    result['frozen_snapshot_hash'] = digest(ctx.telemetry.snapshot)
    result.update(metadata(ctx.alert.model_dump(mode='json'),ctx.telemetry.window.model_dump(mode='json'),
                           ctx.prompts,configuration(provider.name,ctx.budget.limits.model_dump())))
    from .timeline import build_timeline
    result['timeline'] = build_timeline(result)
    if archive is not None:
        save_run(archive, result)
    return result
