import hashlib
import json


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Registry:
    """Store canonical bytes; callers receive copies, never mutable stored payloads."""
    def __init__(self, snapshot_id):
        self.snapshot_id = snapshot_id
        self._items = {}

    def add(self, kind, payload, source_ids, coverage):
        item = dict(snapshot_id=self.snapshot_id, source_kind=kind,
                    source_record_ids=source_ids, service=payload['service'] if kind=='traces' else 'orders', payload=payload,
                    coverage=coverage, schema_version=1,
                    provenance={'adapter': 'snapshot-v1', 'source_ids': source_ids})
        content_hash = digest(item)
        key = 'ev-' + content_hash
        item.update(evidence_id=key, content_hash=content_hash)
        self._items[key] = canonical(item)
        return json.loads(self._items[key])

    def export(self):
        return {key: json.loads(value) for key, value in self._items.items()}

    def restore(self, evidence):
        for key, item in evidence.items():
            content = {k:v for k,v in item.items() if k not in ('evidence_id','content_hash')}
            if (item['snapshot_id'] != self.snapshot_id or digest(content) != item['content_hash']
                    or key != item['evidence_id'] or key != 'ev-' + item['content_hash']):
                raise ValueError('Checkpoint evidence integrity failure')
        self._items = {key:canonical(item) for key,item in evidence.items()}


def validate_citations(report, evidence, supplied):
    """Integrity only. This deliberately does not claim semantic entailment."""
    if isinstance(report, dict):
        for key, value in report.items():
            if key in ('evidence_ids', 'supporting_ids', 'contradicting_ids'):
                if any(i not in evidence or i not in supplied for i in value):
                    raise ValueError('unknown or unsupplied citation')
            else:
                validate_citations(value, evidence, supplied)
    elif isinstance(report, list):
        for item in report:
            validate_citations(item, evidence, supplied)
