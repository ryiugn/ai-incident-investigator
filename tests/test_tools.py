from copy import deepcopy
import pytest
from investigator.demo import demo_case
from investigator.telemetry import Telemetry
from investigator.contracts import ToolRequest


def request(tool='query_logs', **args):
    return ToolRequest(tool=tool, arguments={'service': 'orders', 'window': demo_case()['alert']['window'], **args})


async def test_filter_cutoff_and_stable_overlap_ids():
    snap = demo_case()['telemetry_snapshot']
    late = deepcopy(snap['logs'][0]); late.update(timestamp=snap['window']['end'], source_record_id='late')
    snap['logs'].append(late)
    adapter = Telemetry(snap)
    first = await adapter.query(request())
    assert len(first['items']) == 1
    narrow = await adapter.query(request(window={'start':'2026-09-01T10:02:00Z','end':'2026-09-01T10:04:00Z'}))
    assert first['evidence_ids'] == narrow['evidence_ids']
    first['items'][0]['payload']['message'] = 'mutated'
    assert 'mutated' not in str(adapter.registry.export())


@pytest.mark.parametrize('req', [request(service='shipping'), request(shell='whoami'),
    request('query_metrics', metric_names=['sql']), request(limit=101),
    request(window={'start':'2026-09-01T09:54:00Z','end':'2026-09-01T10:05:00Z'}),
    ToolRequest(tool='shell', arguments={})])
async def test_rejects_unsafe_arguments(req):
    with pytest.raises(ValueError):
        await Telemetry(demo_case()['telemetry_snapshot']).query(req)


async def test_metric_buckets_compute_p95_from_raw_samples_and_missing_is_not_zero():
    snap = demo_case()['telemetry_snapshot']; snap['metrics'] = []
    for i, value in enumerate([1, 2, 3, 4, 100]):
        snap['metrics'].append(dict(source_record_id=str(i), timestamp=f'2026-09-01T10:03:0{i}Z', service='orders',
            metric='db_query_duration_p95', value=value, unit='ms'))
    result = await Telemetry(snap).query(request('query_metrics', metric_names=['db_query_duration_p95']))
    series = result['items'][0]['payload']
    assert series['samples'][0]['value'] == 100
    assert series['samples'][0]['sample_count'] == 5
    assert series['missing_intervals']
    assert result['status'] == 'partial'


async def test_runbook_search_and_changes_are_constrained():
    snap = demo_case()['telemetry_snapshot']
    snap['runbooks'] = [dict(source_record_id='r1', document_id='r1', version='1', section='Timeout', text='Check dependency latency')]
    adapter = Telemetry(snap)
    result = await adapter.query(ToolRequest(tool='search_runbooks', arguments={'query':'dependency', 'limit':1}))
    assert result['items'][0]['payload']['document_id'] == 'r1'
    assert (await adapter.query(request('get_changes')))['status'] == 'empty'
