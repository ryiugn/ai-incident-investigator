import json
from copy import deepcopy
from pathlib import Path
import pytest
from investigator.evidence import digest
from benchmark.label_review import export_packets, import_audit, verify_audit


def corpus(tmp_path):
    (tmp_path/'private').mkdir()
    (tmp_path/'public').mkdir()
    # Synthetic test-only corpus: the public test suite must not need private answers.
    from investigator.demo import demo_case
    labels=[]
    for index in range(2):
        case=demo_case(missing=bool(index))
        case_id=f'test-case-{index}'
        case['opaque_case_id']=case_id
        case['telemetry_snapshot']['snapshot_id']=f'test-snapshot-{index}'
        labels.append(dict(case_id=case_id,generation_group_id=f'test-group-{index}',
            split='development',snapshot_hash=digest(case['telemetry_snapshot']),
            acceptable_diagnoses=['Synthetic test expectation, not a benchmark judgment'],
            review_status='pending_human_audit'))
        (tmp_path/'public'/f'{case_id}.json').write_text(json.dumps(case))
    (tmp_path/'private/labels.json').write_text(json.dumps(labels))
    return labels


def reviewed(packet):
    for row in packet['cases']:
        row.update(reviewer='Human reviewer',reviewed_at='2026-10-03',notes='Checked the exposed observations against every label criterion.',
                   checks={key:True for key in row['checks']})
    return packet


def test_export_does_not_mark_human_audit_complete(tmp_path):
    labels=corpus(tmp_path)
    packet=export_packets(tmp_path,'development')
    assert len(packet['cases'])==2
    assert all(row['reviewer'] is None for row in packet['cases'])
    assert json.loads((tmp_path/'private/labels.json').read_text())==labels
    with pytest.raises(ValueError,match='human'):
        import_audit(tmp_path,packet)


def test_review_import_is_all_or_nothing_and_rejects_stale_source(tmp_path):
    corpus(tmp_path)
    packet=reviewed(export_packets(tmp_path,'development'))
    before=(tmp_path/'private/labels.json').read_bytes()
    packet['cases'][-1]['checks']['answerability']=False
    with pytest.raises(ValueError): import_audit(tmp_path,packet)
    assert (tmp_path/'private/labels.json').read_bytes()==before
    packet['cases'][-1]['checks']['answerability']=True
    path=tmp_path/'public'/f"{packet['cases'][0]['case_id']}.json"
    case=json.loads(path.read_text());case['alert']['symptom']='Changed alert'
    path.write_text(json.dumps(case))
    with pytest.raises(ValueError,match='changed'): import_audit(tmp_path,packet)


def test_import_freezes_review_and_detects_tampering(tmp_path):
    corpus(tmp_path)
    packet=reviewed(export_packets(tmp_path,'development'))
    import_audit(tmp_path,packet)
    verify_audit(tmp_path,'development')
    labels=json.loads((tmp_path/'private/labels.json').read_text())
    labels[0]['acceptable_diagnoses']=['different']
    (tmp_path/'private/labels.json').write_text(json.dumps(labels))
    with pytest.raises(ValueError,match='changed'): verify_audit(tmp_path,'development')


def test_duplicate_review_cannot_hide_missing_case(tmp_path):
    corpus(tmp_path)
    packet=reviewed(export_packets(tmp_path,'development'))
    packet['cases'][1]=deepcopy(packet['cases'][0])
    with pytest.raises(ValueError,match='exactly once'): import_audit(tmp_path,packet)



def test_paid_batch_rejects_unaudited_labels_before_starting_docker(tmp_path,monkeypatch):
    from benchmark.evaluate import run_batch
    import subprocess
    corpus(tmp_path)
    config=json.loads(Path('benchmark/configs/development.json').read_text())
    config['provider']='anthropic'
    def no_process(*args,**kwargs):
        raise AssertionError('No process may start before audit validation')
    monkeypatch.setattr(subprocess,'run',no_process)
    with pytest.raises(ValueError,match='human label audit'):
        run_batch(config,root=tmp_path,approved_budget_usd=10)


def test_freeze_cannot_substitute_empty_attestation(tmp_path):
    corpus(tmp_path)
    import_audit(tmp_path,reviewed(export_packets(tmp_path,'development')))
    path=tmp_path/'private/reviewed-development.json'
    freeze=json.loads(path.read_text())
    freeze['review']['cases']=[]
    freeze['review']['label_hash']=digest([])
    path.write_text(json.dumps(freeze))
    with pytest.raises(ValueError,match='attestation'): verify_audit(tmp_path,'development')


def test_freeze_attestation_must_reconstruct_current_labels(tmp_path):
    corpus(tmp_path)
    import_audit(tmp_path,reviewed(export_packets(tmp_path,'development')))
    path=tmp_path/'private/reviewed-development.json'
    freeze=json.loads(path.read_text())
    rows=freeze['review']['cases']
    rows[0]['label']['acceptable_diagnoses']=['An unrelated original judgment']
    freeze['review']['label_hash']=digest([row['label'] for row in rows])
    path.write_text(json.dumps(freeze))
    with pytest.raises(ValueError,match='attestation'): verify_audit(tmp_path,'development')
