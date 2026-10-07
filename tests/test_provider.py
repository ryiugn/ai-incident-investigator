import pytest


@pytest.fixture(autouse=True)
def clean_provider_environment(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_BASE_URL',raising=False)


def test_real_provider_requires_explicit_budget_and_credentials():
    from investigator.provider import AnthropicProvider
    with pytest.raises(ValueError):
        AnthropicProvider(api_key='unused', approved_budget_usd=0)
    with pytest.raises(ValueError):
        AnthropicProvider(api_key='', approved_budget_usd=1)


async def test_provider_uses_structured_output_without_sdk_retries():
    from investigator.provider import AnthropicProvider
    from investigator.contracts import Report
    from investigator.demo import demo_case
    from investigator.provider import ScriptedProvider
    from types import SimpleNamespace
    report, _ = await ScriptedProvider().respond({'evidence': []}, Report, 1000, 20)
    import json
    class Messages:
        async def create(self, **kwargs):
            assert kwargs['output_config']['format']['type'] == 'json_schema'
            assert kwargs['max_tokens'] == 1000
            return SimpleNamespace(content=[SimpleNamespace(type='text', text=json.dumps(report))],
                stop_reason='end_turn', usage=SimpleNamespace(input_tokens=100, output_tokens=80,
                    cache_read_input_tokens=0, cache_creation_input_tokens=0))
    provider = AnthropicProvider(api_key='unused', approved_budget_usd=1)
    provider.client = SimpleNamespace(messages=Messages())
    raw, usage = await provider.respond({'evidence': []}, Report, 1000, 20)
    assert raw['status'] == 'insufficient_evidence'
    assert usage['input_tokens'] == 100


def test_hosted_schema_transforms_constraints_and_preserves_tool_arguments():
    from investigator.provider import provider_schema
    from investigator.contracts import Decision, Report
    schema=provider_schema(Decision)
    variants=schema['$defs']['ToolRequest']['anyOf']
    logs=next(v for v in variants if v['properties']['tool']['enum']==['query_logs'])
    assert 'window' in logs['properties']['arguments']['properties']
    assert logs['properties']['arguments']['additionalProperties'] is False
    assert 'maxLength' not in provider_schema(Report)['properties']['uncertainty']


async def test_paid_timeout_reservation_survives_provider_restart(tmp_path):
    from investigator.provider import AnthropicProvider
    from investigator.contracts import Report
    from types import SimpleNamespace
    import json
    class TimeoutMessages:
        async def create(self,**kwargs): raise TimeoutError()
    ledger=tmp_path/'spend.json'
    provider=AnthropicProvider(api_key='unused',approved_budget_usd=1,ledger_path=ledger)
    provider.client=SimpleNamespace(messages=TimeoutMessages())
    with pytest.raises(TimeoutError): await provider.respond({'evidence':[]},Report,1000,20)
    restarted=AnthropicProvider(api_key='unused',approved_budget_usd=1,ledger_path=ledger)
    assert restarted.reserved_or_spent>0
    assert json.loads(ledger.read_text())['reserved_or_spent']==restarted.reserved_or_spent


def test_custom_endpoint_is_rejected_before_client_creation(monkeypatch):
    from investigator.provider import validate_endpoint
    monkeypatch.setenv('ANTHROPIC_BASE_URL','https://example.invalid/anthropic')
    with pytest.raises(ValueError,match='endpoint'):
        validate_endpoint()


def test_provider_window_schema_leaves_timestamp_validation_to_application():
    from investigator.provider import provider_schema
    from investigator.contracts import Decision
    schema=provider_schema(Decision)
    assert 'format' not in schema['$defs']['Window']['properties']['start']
    assert 'format' not in schema['$defs']['Window']['properties']['end']


async def test_two_preconstructed_providers_cannot_overwrite_shared_reservations(tmp_path):
    from investigator.provider import AnthropicProvider
    from investigator.contracts import Report
    from types import SimpleNamespace
    import json
    class TimeoutMessages:
        async def create(self,**kwargs): raise TimeoutError()
    ledger = tmp_path/'shared.json'
    a = AnthropicProvider(api_key='unused',approved_budget_usd=1,ledger_path=ledger)
    b = AnthropicProvider(api_key='unused',approved_budget_usd=1,ledger_path=ledger)
    a.client = b.client = SimpleNamespace(messages=TimeoutMessages())
    with pytest.raises(TimeoutError): await a.respond({'evidence':[]},Report,1000,20)
    first = json.loads(ledger.read_text())['reserved_or_spent']
    with pytest.raises(TimeoutError): await b.respond({'evidence':[]},Report,1000,20)
    assert json.loads(ledger.read_text())['reserved_or_spent'] == pytest.approx(2*first)


async def test_shared_ceiling_prevents_second_dispatch_with_stale_provider(tmp_path):
    from investigator.provider import AnthropicProvider
    from investigator.contracts import Report
    from types import SimpleNamespace
    class TimeoutMessages:
        async def create(self,**kwargs): raise TimeoutError()
    payload = {'evidence':[]}
    ceiling = (AnthropicProvider.estimate_input(payload,Report)+5000)/1e6 * 1.5
    ledger = tmp_path/'shared.json'
    a = AnthropicProvider(api_key='unused',approved_budget_usd=ceiling,ledger_path=ledger)
    b = AnthropicProvider(api_key='unused',approved_budget_usd=ceiling,ledger_path=ledger)
    a.client = b.client = SimpleNamespace(messages=TimeoutMessages())
    with pytest.raises(TimeoutError): await a.respond(payload,Report,1000,20)
    with pytest.raises(ValueError,match='ceiling'): await b.respond(payload,Report,1000,20)
