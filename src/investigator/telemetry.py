from copy import deepcopy
from datetime import datetime, timedelta
import math
import re
from .contracts import Window, TOOL_SCHEMAS
from .evidence import Registry
from .snapshot import Snapshot


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


class Telemetry:
    def __init__(self, snapshot):
        self.snapshot = Snapshot.model_validate(snapshot).model_dump(mode='json',exclude_none=True)
        self.window = Window.model_validate(snapshot['window'])
        self.registry = Registry(snapshot['snapshot_id'])

    def validate(self, request):
        if request.tool not in TOOL_SCHEMAS:
            raise ValueError('tool not allowed')
        args = TOOL_SCHEMAS[request.tool].model_validate(request.arguments)
        if hasattr(args, 'window') and not (self.window.start <= args.window.start < args.window.end <= self.window.end):
            raise ValueError('out_of_scope')
        return args

    async def query(self, request):
        args = self.validate(request)
        window = getattr(args, 'window', self.window)
        coverage = dict(**window.model_dump(mode='json'), complete=self.snapshot['complete'])
        if request.tool == 'query_traces':
            coverage['complete'] = bool(coverage['complete'] and self.snapshot.get('traces_complete')
                                        and 'traces' in self.snapshot)
            records = [r for r in self.snapshot.get('traces', []) if r['service'] == args.service
                       and window.start <= timestamp(r['start_time']) < window.end
                       and (args.trace_id is None or r['trace_id'] == args.trace_id)]
            if any(timestamp(r['end_time'])>window.end for r in records):
                coverage['complete']=False
            records=[r for r in records if timestamp(r['end_time'])<=window.end]
            records.sort(key=lambda r: (timestamp(r['start_time']), r['source_record_id']))
            items = [self.registry.add('traces', r, [r['source_record_id']],
                     {'event_time':r['start_time'], 'end_time':r['end_time']}) for r in records[:args.limit]]
            return self.envelope(items, len(records), coverage)
        if request.tool == 'search_runbooks':
            words = set(re.findall(r'[a-z0-9]+', args.query.lower()))
            ranked = []
            for record in self.snapshot.get('runbooks', []):
                score = len(words & set(re.findall(r'[a-z0-9]+', record['text'].lower())))
                if score:
                    ranked.append((score, record))
            ranked.sort(key=lambda pair: (-pair[0], pair[1]['source_record_id']))
            items = [self.registry.add('runbooks', r, [r['source_record_id']], {'version': r['version']})
                     for _, r in ranked[:args.limit]]
            return self.envelope(items, len(ranked), coverage)
        kind = {'query_logs': 'logs', 'query_metrics': 'metrics', 'get_changes': 'changes'}[request.tool]
        records = [r for r in self.snapshot[kind] if r['service'] == args.service
                   and window.start <= timestamp(r['timestamp']) < window.end]
        if kind == 'logs':
            records = [r for r in records if (args.levels is None or r['level'] in args.levels)
                       and (args.event_codes is None or r['event_code'] in args.event_codes)
                       and (args.request_id is None or r.get('request_id') == args.request_id)]
        elif kind == 'metrics':
            records = [r for r in records if r['metric'] in args.metric_names]
            return self.metric_series(records, args, coverage)
        records.sort(key=lambda r: (r['timestamp'], r['source_record_id']))
        total = len(records)
        records = records[:getattr(args, 'limit', 100)]
        items = [self.registry.add(kind, r, [r['source_record_id']], {'event_time': r['timestamp']}) for r in records]
        return self.envelope(items, total, coverage)

    @staticmethod
    def envelope(items, total, coverage):
        return dict(status=('ok' if items else 'empty') if coverage['complete'] else 'partial',
                    items=items, evidence_ids=[r['evidence_id'] for r in items], coverage=coverage,
                    truncated=total > len(items), total_matches=total, error=None)

    def metric_series(self, records, args, coverage):
        items = []
        for name in args.metric_names:
            rows = [r for r in records if r['metric'] == name]
            samples, gaps, source_ids = [], [], []
            cursor = args.window.start
            while cursor < args.window.end:
                end = min(cursor + timedelta(seconds=args.step_seconds), args.window.end)
                bucket = [r for r in rows if cursor <= timestamp(r['timestamp']) < end]
                interval = {'start': cursor.isoformat(), 'end': end.isoformat()}
                if bucket:
                    values = sorted(r['value'] for r in bucket)
                    value = (values[math.ceil(.95 * len(values)) - 1] if name.endswith('_p95')
                             else sum(values) if name.endswith('_count') else max(values))
                    samples.append(dict(**interval, value=value, sample_count=len(values)))
                    source_ids.extend(r['source_record_id'] for r in bucket)
                else:
                    if gaps and gaps[-1]['end']==interval['start']:
                        gaps[-1]['end']=interval['end']
                    else:
                        gaps.append(interval)
                cursor = end
            metric_coverage = {**coverage, 'complete': coverage['complete'] and not gaps}
            payload = dict(metric=name, unit=rows[0]['unit'] if rows else 'unknown',
                           aggregation='nearest_rank_p95' if name.endswith('_p95') else 'sum' if name.endswith('_count') else 'max',
                           samples=samples, missing_intervals=gaps, window=args.window.model_dump(mode='json'), step_seconds=args.step_seconds)
            items.append(self.registry.add('metrics', payload, sorted(source_ids), metric_coverage))
        coverage = {**coverage, 'complete': all(i['coverage']['complete'] for i in items)}
        return self.envelope(items, len(items), coverage)
