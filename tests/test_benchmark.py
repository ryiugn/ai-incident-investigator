import pytest


def test_metrics_include_failures_and_unreviewed_is_pending():
    from benchmark.metrics import summarize
    rows = [dict(run_id='a', answerability='answerable', valid=True, status='diagnosis', review={'correctness':2,'support':2,'forbidden_overclaim':False,'claims':['supported']}, usage={'elapsed_ms':10}),
            dict(run_id='b', answerability='answerable', valid=False, status='error', review=None, usage={'elapsed_ms':90}),
            dict(run_id='c', answerability='insufficient', valid=True, status='insufficient_evidence', review={'abstention':True,'claims':[]}, usage={'elapsed_ms':20})]
    result = summarize(rows)
    assert result['scheduled_runs'] == 3
    assert result['supported_diagnosis']['denominator'] == 2
    assert result['supported_diagnosis']['numerator'] == 1
    assert result['valid_completion']['numerator'] == 2
    assert result['useful_outcome']['denominator'] == 3
    assert result['zero_claim_reports'] == 1
    rows[0]['review'] = None
    assert summarize(rows)['supported_diagnosis']['value'] is None


def test_group_split_leakage_rejected():
    from benchmark.dataset import audit_labels
    labels=[dict(case_id='a',generation_group_id='g',split='development'),dict(case_id='b',generation_group_id='g',split='held_out')]
    with pytest.raises(ValueError,match='group'):
        audit_labels(labels)


def test_payload_audit_detects_private_values():
    from benchmark.dataset import audit_payload
    with pytest.raises(ValueError):
        audit_payload({'alert':'secret-control-121'}, ['secret-control-121'])


def test_paired_bootstrap_preserves_capture_groups():
    from benchmark.metrics import paired_bootstrap
    rows = [dict(group='g1', workflow='fixed', score=0),dict(group='g1',workflow='adaptive',score=1),
            dict(group='g2',workflow='fixed',score=0),dict(group='g2',workflow='adaptive',score=1)]
    result = paired_bootstrap(rows, seed=11)
    assert result['difference'] == 1
    assert result['interval'] == [1,1]
