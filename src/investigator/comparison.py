"""Descriptive public run comparison; never private-label scoring."""
from .evidence import digest


def compare_runs(left_id,left,right_id,right,store):
    issues=[]
    snapshot_key='frozen_snapshot_hash' if left.get('frozen_snapshot_hash') and right.get('frozen_snapshot_hash') else 'snapshot_hash'
    if not left.get(snapshot_key) or left.get(snapshot_key)!=right.get(snapshot_key):
        issues.append('Snapshot fingerprints differ or are unavailable.')
    if not left.get('alert_hash') or left.get('alert_hash')!=right.get('alert_hash'):
        issues.append('Alert fingerprints differ or are unavailable.')
    if {left.get('workflow'),right.get('workflow')}!={'fixed','adaptive'}:
        issues.append('Paired comparison requires one fixed and one adaptive run.')
    if not left.get('configuration') or not right.get('configuration'):
        issues.append('Legacy configuration metadata is unavailable; reproducibility cannot be established.')
    elif digest(left['configuration'])!=digest(right['configuration']):
        issues.append('Run configurations differ.')
    if left.get('provider')!=right.get('provider'):
        issues.append('Providers differ.')
    def side(run_id,result):
        config=result.get('configuration')
        return dict(run_id=run_id,workflow=result.get('workflow'),provider=result.get('provider'),
            configuration=config,configuration_hash=digest(config) if config else None,
            snapshot_hash=result.get('snapshot_hash'),alert_hash=result.get('alert_hash'),
            frozen_snapshot_hash=result.get('frozen_snapshot_hash'),
            prompt_fingerprint=result.get('prompt_fingerprint'),
            queries=[e for e in result.get('events',[]) if 'tool' in e],
            evidence=result.get('evidence',{}),report=result.get('report'),usage=result.get('usage',{}),
            review_coverage=store.get(run_id,result)['coverage'])
    return dict(paired=not issues,incompatibilities=issues,left=side(left_id,left),right=side(right_id,right),
        findings_status='Public evidence comparison; no benchmark correctness or winner inferred.')
