import pytest
from investigator.runner import RunContext
from investigator.provider import ScriptedProvider
from investigator.budgets import Limits
from investigator.telemetry import Telemetry
from investigator.demo import demo_case
from investigator.contracts import Decision, ToolRequest


async def test_out_of_scope_query_returns_actionable_boundary_without_dispatch():
    ctx=RunContext(demo_case(),ScriptedProvider(),Limits(),Telemetry)
    request=ToolRequest(tool='query_logs',arguments={'service':'orders','window':{'start':'2020-01-01T00:00:00Z','end':'2020-01-01T00:01:00Z'}})
    await ctx.dispatch(request)
    event=ctx.payload(Decision)['tool_events'][-1]
    assert event['error']=='invalid_arguments'
    assert event['validation_reason']=='out_of_scope'
    assert event['arguments']==request.arguments
    assert ctx.payload(Decision)['query_window']==ctx.telemetry.window.model_dump(mode='json')
    assert ctx.budget.usage['tool_dispatches']==0
