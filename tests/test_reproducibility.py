from investigator.runner import run_investigation
from investigator.provider import ScriptedProvider
from investigator.demo import demo_case
from investigator.checkpoint import Investigations

async def test_fixed_and_durable_reproducibility_is_bound_to_alert_and_configuration(tmp_path):
    case=demo_case(); provider=ScriptedProvider()
    fixed=await run_investigation(case,provider,workflow='fixed')
    service=Investigations(tmp_path/'state.sqlite',provider)
    run_id=service.create(case)
    adaptive=(await service.drive(run_id))['result']
    assert fixed.get('configuration')
    assert fixed['configuration']==adaptive['configuration']
    assert fixed['alert_hash']==adaptive['alert_hash']
    assert fixed['frozen_snapshot_hash']==adaptive['frozen_snapshot_hash']
    assert fixed['prompt_fingerprint']!=adaptive['prompt_fingerprint']
