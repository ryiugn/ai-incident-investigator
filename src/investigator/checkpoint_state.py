"""Versioned JSON investigation data. Runtime objects never enter checkpoints."""
import time
from copy import deepcopy
from .contracts import Alert, Decision, Report
from .snapshot import Snapshot
from .budgets import Limits
from .runner import RunContext
from .evidence import digest, canonical

VERSION = 1


def initial(case, provider, limits, adapter_factory, run_id, case_id):
    public = {'alert': Alert.model_validate(case['alert']).model_dump(mode='json'),
              'telemetry_snapshot': Snapshot.model_validate(case['telemetry_snapshot']).model_dump(mode='json', exclude_none=True)}
    ctx = RunContext(public, provider, limits, adapter_factory)
    ctx.run_id = run_id
    state = dict(version=VERSION, run_id=run_id, case_id=case_id, case=public, created_at=time.time(),
                 snapshot_hash=digest(public['telemetry_snapshot']), provider=provider.name,
                 paid=provider.paid, provider_binding=provider_binding(provider), revision=0,
                 pending=None, approved_query=None, route='validate_alert')
    from .reproducibility import configuration
    state['configuration'] = configuration(provider.name,limits.model_dump())
    return capture(ctx, state)


def provider_binding(provider):
    ledger = getattr(provider, 'ledger_path', None)
    return dict(name=provider.name, paid=provider.paid, ceiling=getattr(provider,'ceiling',None),
                ledger=digest(str(ledger.resolve())) if ledger else None)


def validate(state):
    if state.get('version') != VERSION:
        raise ValueError('Unsupported checkpoint version; start a new investigation.')
    if digest(state['case']['telemetry_snapshot']) != state['snapshot_hash']:
        raise ValueError('Snapshot identity mismatch; cannot resume.')


def restore(state, provider, adapter_factory):
    validate(state)
    if hasattr(provider,'refresh_spend'):
        provider.refresh_spend()
    if state['provider_binding'] != provider_binding(provider):
        raise ValueError('Provider or spending ledger differs; restore the original server configuration.')
    minimum_spend = state['usage']['estimated_cost_usd'] + sum(r['reserved_cost_usd'] for r in state['usage']['unknown_usage_reservations'])
    if provider.paid and getattr(provider,'reserved_or_spent',minimum_spend) + 1e-10 < minimum_spend:
        raise ValueError('Persistent spending ledger is missing or behind this investigation; cannot resume.')
    ctx = RunContext(state['case'], provider, Limits.model_validate(state['limits']), adapter_factory)
    ctx.run_id = state['run_id']
    for name in ('events','nodes','prompts','cache','no_progress','reason'):
        setattr(ctx, name, deepcopy(state[name]))
    for name in ('hypotheses','hypothesis_history','execution_steps'):
        setattr(ctx, name, deepcopy(state.get(name, [])))
    ctx.supplied = set(state['supplied'])
    ctx.decision = Decision.model_validate(state['decision']) if state['decision'] else None
    ctx.report = Report.model_validate(state['report']) if state['report'] else None
    ctx.telemetry.registry.restore(state['evidence'])
    ctx.budget.usage = deepcopy(state['usage'])
    ctx.budget.start = time.monotonic() - state['usage']['elapsed_ms']/1000
    return ctx


def capture(ctx, previous):
    state = deepcopy(previous)
    state.update({name:deepcopy(getattr(ctx,name)) for name in ('events','nodes','prompts','cache','no_progress','reason')})
    state.update(hypotheses=deepcopy(ctx.hypotheses), hypothesis_history=deepcopy(ctx.hypothesis_history))
    state['execution_steps'] = deepcopy(ctx.execution_steps)
    state.update(evidence=ctx.telemetry.registry.export(), supplied=sorted(ctx.supplied),
                 decision=ctx.decision.model_dump(mode='json') if ctx.decision else None,
                 report=ctx.report.model_dump(mode='json') if ctx.report else None,
                 usage=deepcopy(ctx.budget.finish()), limits=ctx.budget.limits.model_dump())
    return state


def result(state):
    from .reproducibility import metadata
    value = dict(**metadata(state['case']['alert'],state['case']['telemetry_snapshot']['window'],
                           state['prompts'],state.get('configuration')),run_id=state['run_id'], workflow='adaptive', provider=state['provider'],
                report=state['report'], termination_reason=state['reason'], evidence=state['evidence'],
                events=state['events'], nodes=state['nodes'], usage=state['usage'],
                limits=state['limits'], snapshot_hash=state['snapshot_hash'], frozen_snapshot_hash=state['snapshot_hash'], schema_version=1)
    value.update(hypotheses=deepcopy(state.get('hypotheses', [])),
                 execution_steps=deepcopy(state.get('execution_steps', [])),
                 hypothesis_history=deepcopy(state.get('hypothesis_history', [])))
    from .timeline import build_timeline
    value['timeline'] = build_timeline(value)
    return value
