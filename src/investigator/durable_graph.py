"""Resumable adaptive graph: data in state, runtime services in the closure."""
from copy import deepcopy
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from . import checkpoint_state as data
from .contracts import Decision, ToolRequest
from .budgets import Exhausted
from .evidence import digest
from .execution import begin, complete


class DurableState(TypedDict):
    investigation: dict


def build_durable_graph(service, saver):
    def node(name, action):
        async def execute(graph_state):
            previous = graph_state['investigation']
            data.validate(previous)
            revision, run_id = previous['revision'], previous['run_id']
            saved = service.journal(run_id,revision,name)
            if saved:
                if saved[0] != 'completed':
                    raise ValueError('Unknown external-call outcome; automatic replay disabled.')
                return {'investigation':saved[1]}
            ctx = data.restore(previous,service.provider,service.adapter_factory)
            state = deepcopy(previous)

            def reserve(kind, timeout):
                reserved = data.capture(ctx,state)
                reserved['usage']['elapsed_ms'] += round(timeout*1000)
                reserved['uncertain_call'] = kind
                service.record(run_id,revision,name,'dispatching',reserved)

            ctx.before_dispatch = reserve
            boundary = begin(ctx)
            if name != 'finalize':
                ctx.nodes.append(name)
            route = await action(ctx,state)
            complete(ctx, name, route, boundary)
            output = data.capture(ctx,state)
            output.update(revision=revision+1,route=route)
            service.record(run_id,revision,name,'completed',output)
            return {'investigation':output}
        return execute

    async def validate_alert(ctx,state):
        return 'triage'

    async def decide(ctx,state):
        try:
            ctx.decision = await ctx.model(Decision)
            ctx.events.append(dict(summary=ctx.decision.summary,action=ctx.decision.action))
            return 'guard_action'
        except Exhausted as error:
            ctx.reason = str(error)
            return 'finalize'

    async def assess(ctx,state):
        if ctx.no_progress >= 2:
            ctx.reason = 'no_progress'
            return 'finalize'
        return await decide(ctx,state)

    async def guard_action(ctx,state):
        if ctx.decision.action != 'collect':
            ctx.reason = ctx.decision.action
            return 'finalize'
        request = ctx.decision.tool_request
        try:
            args = ctx.telemetry.validate(request)
        except ValueError:
            # Existing dispatch records bounded validation feedback without execution.
            await ctx.dispatch(request)
            return 'assess'
        query = dict(tool=request.tool,arguments=args.model_dump(mode='json'))
        ctx.decision = ctx.decision.model_copy(update={'tool_request':ToolRequest.model_validate(query)})
        window = getattr(args,'window',None)
        if window and not (ctx.alert.window.start <= window.start < window.end <= ctx.alert.window.end):
            try:
                ctx.budget.check_time()
                if ctx.budget.usage['tool_dispatches'] >= ctx.budget.limits.tool_dispatches:
                    raise Exhausted('tool_budget')
            except Exhausted as error:
                ctx.reason = str(error)
                return 'finalize'
            state['pending'] = dict(approval_id=digest(dict(run_id=ctx.run_id,revision=state['revision']+1,query=query)),
                query=query, requested_window=window.model_dump(mode='json'),
                original_window=ctx.alert.window.model_dump(mode='json'),
                allowed_scope=ctx.telemetry.window.model_dump(mode='json'), summary=ctx.decision.summary,
                reason='This query extends beyond the original alert window within the frozen snapshot horizon.')
            ctx.events.append(dict(status='awaiting_approval',summary='Paused before an expanded evidence query.'))
            ctx.nodes.append('pause_for_approval')
            return 'human_approval'
        return 'collect_evidence'

    async def human_approval(ctx,state):
        pending = state['pending']
        # No external calls or durable side effects before interrupt. All mutation
        # before it is discarded and deterministically reconstructed on replay.
        answer = interrupt(pending)
        if answer['approval_id'] != pending['approval_id'] or answer['revision'] != state['revision']:
            raise ValueError('Stale approval')
        state['pending'] = None
        ctx.nodes.append('resume_' + answer['decision'])
        ctx.events.append(dict(status='resumed',summary='Expanded evidence query ' + ('approved.' if answer['decision']=='approve' else 'declined.')))
        if answer['decision'] == 'decline':
            ctx.reason = 'approval_declined'
            return 'finalize'
        state['approved_query'] = digest(pending['query'])
        return 'collect_evidence'

    async def collect_evidence(ctx,state):
        request = ctx.decision.tool_request
        args = ctx.telemetry.validate(request)
        window = getattr(args,'window',None)
        expanded = window and not (ctx.alert.window.start <= window.start < window.end <= ctx.alert.window.end)
        if expanded and state['approved_query'] != digest(request.model_dump(mode='json')):
            raise ValueError('Expanded query lacks exact approval')
        try:
            await ctx.dispatch(request)
            state['approved_query'] = None
            return 'assess'
        except Exhausted as error:
            ctx.reason = str(error)
            return 'finalize'

    async def finalize(ctx,state):
        await ctx.finalize()
        if ctx.reason == 'approval_declined':
            ctx.report = ctx.report.model_copy(update={'missing_evidence':[
                *ctx.report.missing_evidence,'Expanded evidence query declined by the user; assessment uses only evidence already collected.']})
        return 'end'

    graph = StateGraph(DurableState)
    for name, action in [('validate_alert',validate_alert),('triage',decide),('guard_action',guard_action),
                         ('human_approval',human_approval),('collect_evidence',collect_evidence),('assess',assess),('finalize',finalize)]:
        graph.add_node(name,node(name,action))
        graph.add_conditional_edges(name,lambda s:s['investigation']['route'],
            {key:key for key in ('triage','guard_action','human_approval','collect_evidence','assess','finalize')} | {'end':END})
    graph.add_edge(START,'validate_alert')
    return graph.compile(checkpointer=saver)
