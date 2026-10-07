"""Explicit opt-in; never inject faults during ordinary unit tests."""
import os
import pytest


@pytest.mark.live
@pytest.mark.skipif(os.environ.get('RUN_LIVE') != '1', reason='Set RUN_LIVE=1 with the isolated Compose environment running')
@pytest.mark.parametrize('family', ['dependency_timeout', 'lock_contention', 'pool_exhaustion', 'slow_query', 'config_error'])
def test_fault_capture_and_cleanup(family, tmp_path):
    from environment.capture import capture
    from investigator.telemetry import Telemetry
    from investigator.contracts import ToolRequest
    import asyncio, json
    case, label = capture(family, seed=17)
    assert label['provenance']['healthy_verified']
    assert label['provenance']['fault_verified']
    assert label['provenance']['cleanup_verified']
    path = tmp_path / 'snapshot.json'
    path.write_text(json.dumps(case))
    reloaded = json.loads(path.read_text())
    request = ToolRequest(tool='query_logs', arguments={'service':'orders','window':case['alert']['window']})
    assert asyncio.run(Telemetry(case['telemetry_snapshot']).query(request)) == asyncio.run(Telemetry(reloaded['telemetry_snapshot']).query(request))
