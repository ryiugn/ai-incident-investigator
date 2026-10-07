from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from .contracts import Decision
from .budgets import Exhausted


class State(TypedDict):
    route: str


def build_graph(ctx):
    """Runtime dependencies are per-run closures, never serialized graph state."""
    async def validate_alert(state):
        ctx.nodes.append('validate_alert')
        return {'route':'triage'}

    async def decide(name):
        ctx.nodes.append(name)
        try:
            ctx.decision = await ctx.model(Decision)
            ctx.events.append(dict(summary=ctx.decision.summary, action=ctx.decision.action))
            return {'route':'guard_action'}
        except Exhausted as error:
            ctx.reason = str(error)
            return {'route':'finalize'}

    async def triage(state):
        return await decide('triage')

    async def assess(state):
        if ctx.no_progress >= 2:
            ctx.nodes.append('assess'); ctx.reason = 'no_progress'
            return {'route':'finalize'}
        return await decide('assess')

    async def guard_action(state):
        ctx.nodes.append('guard_action')
        if ctx.decision.action != 'collect':
            ctx.reason = ctx.decision.action
            return {'route':'finalize'}
        return {'route':'collect_evidence'}

    async def collect_evidence(state):
        ctx.nodes.append('collect_evidence')
        try:
            await ctx.dispatch(ctx.decision.tool_request)
            return {'route':'assess'}
        except Exhausted as error:
            ctx.reason = str(error)
            return {'route':'finalize'}

    async def finalize(state):
        await ctx.finalize()
        return {'route':'end'}

    graph = StateGraph(State)
    for node in (validate_alert, triage, guard_action, collect_evidence, assess, finalize):
        graph.add_node(node.__name__, node)
    graph.add_edge(START, 'validate_alert')
    graph.add_edge('validate_alert', 'triage')
    for name in ('triage', 'guard_action', 'collect_evidence', 'assess'):
        graph.add_conditional_edges(name, lambda state: state['route'],
            {key:key for key in ('guard_action','collect_evidence','assess','finalize')})
    graph.add_edge('finalize', END)
    return graph.compile()
