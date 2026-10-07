"""Event-time projection of collected public evidence (not unqueried snapshot data)."""
from datetime import datetime, timezone


def build_timeline(result):
    events = []

    def utc(value):
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Timeline timestamps require a timezone')
        return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

    def add(kind, start, label, end=None, **fields):
        event = dict(kind=kind, start=utc(start), label=label, **fields)
        if end is not None:
            event['end'] = utc(end)
        events.append(event)

    alert = result.get('alert') or {}
    window = alert.get('window') or {}
    if window:
        add('alert_start', window['start'], 'Alert window starts')
    if alert.get('triggered_at'):
        add('alert_trigger', alert['triggered_at'], alert.get('symptom', 'Alert triggered'))
    if window:
        add('alert_end', window['end'], 'Alert window ends (exclusive)')
    # Query order survives canonical JSON/checkpoint object-key reordering.
    expanded=[]
    parse=lambda t: datetime.fromisoformat(t.replace('Z','+00:00'))
    if window:
        for activity in result.get('events',[]):
            query=activity.get('arguments',{}).get('window')
            if query and activity.get('status') in ('ok','partial','empty') and (
                parse(query['start'])<parse(window['start']) or parse(query['end'])>parse(window['end'])):
                interval=dict(tool=activity['tool'],start=utc(query['start']),end=utc(query['end']))
                if interval not in expanded: expanded.append(interval)
    order = {}
    for event in result.get('events', []):
        for evidence_id in event.get('result', {}).get('evidence_ids', []):
            order.setdefault(evidence_id, len(order) + 1)
    evidence = result.get('evidence', {})
    for evidence_id in evidence:
        order.setdefault(evidence_id, len(order) + 1)
    for evidence_id, item in evidence.items():
        payload = item['payload']
        common = dict(evidence_id=evidence_id, collection_order=order[evidence_id])
        kind = item['source_kind']
        if kind in ('logs', 'changes'):
            label = payload.get('message', payload.get('revision', kind))
            add('log' if kind == 'logs' else 'change', payload['timestamp'], label, **common)
        elif kind == 'metrics':
            for sample in payload.get('samples', []):
                add('metric_sample', sample['start'], payload['metric'], end=sample['end'],
                    value=sample['value'], unit=payload.get('unit'), sample_count=sample.get('sample_count'), **common)
            for gap in payload.get('missing_intervals', []):
                add('metric_gap', gap['start'], payload['metric'] + ': missing observations', end=gap['end'], **common)
        elif kind == 'traces':
            add('trace_span', payload['start_time'], payload.get('operation', 'Trace span'),
                end=payload['end_time'], trace_id=payload.get('trace_id'),
                span_id=payload.get('span_id'), service=payload.get('service'), **common)
    # Compare actual instants: fractional timestamp strings do not sort reliably.
    events.sort(key=lambda e: datetime.fromisoformat(e['start'].replace('Z', '+00:00')))
    return dict(timezone='UTC', scope=dict(alert_window=window or None,
                snapshot_window=result.get('snapshot_window'),expanded_windows=expanded), events=events)
