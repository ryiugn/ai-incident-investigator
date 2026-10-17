"""Public, completed-boundary playback; never reconstruct model reasoning."""
from copy import deepcopy


def snapshot(ctx):
    return dict(evidence_ids=sorted(ctx.telemetry.registry.export()),
                usage=deepcopy(ctx.budget.finish()), no_progress=ctx.no_progress,
                report_status=ctx.report.status if ctx.report else None,
                hypotheses=deepcopy(ctx.hypotheses))


def begin(ctx):
    return snapshot(ctx), len(ctx.events), len(ctx.prompts), ctx.decision


def complete(ctx, node, route, boundary):
    before, event_index, prompt_index, previous_decision = boundary
    inputs = []
    for prompt in ctx.prompts[prompt_index:]:
        payload = prompt['payload']
        inputs.append(dict(request=prompt['request'], contract=prompt['contract'],
                           evidence_ids=[e['evidence_id'] for e in payload['evidence']],
                           evidence_selection=deepcopy(payload['evidence_selection'])))
    ctx.execution_steps.append(dict(
        version=1, sequence=len(ctx.execution_steps)+1, node=node,
        status='completed', route=route, before=before, after=snapshot(ctx),
        decision=ctx.decision.model_dump(mode='json') if ctx.decision else None,
        decision_origin=('produced_here' if node in ('triage','assess') and ctx.decision is not previous_decision
                         else 'retained') if ctx.decision else 'none',
        events=deepcopy(ctx.events[event_index:]), model_inputs=inputs,
        stop_reason=ctx.reason if route in ('finalize','end') else None))
