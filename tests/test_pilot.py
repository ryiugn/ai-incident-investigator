import json
from pathlib import Path
import pytest
from benchmark.evaluate import select_cases


def test_exploratory_pilot_is_small_development_only():
    labels=[dict(case_id=str(i),split='development') for i in range(6)]
    config=dict(split='development',repeats=1,case_ids=['0','2'])
    assert [row['case_id'] for row in select_cases(labels,config,True)]==['0','2']
    for bad in [dict(config,split='held_out'),dict(config,repeats=3),dict(config,case_ids=['0','0']),dict(config,case_ids=['unknown']),dict(config,case_ids=[str(i) for i in range(6)])]:
        with pytest.raises(ValueError): select_cases(labels,bad,True)


def test_exploratory_summary_remains_explicit_even_without_successful_runs(tmp_path):
    from benchmark.evaluate import write_summary
    manifest=dict(batch_id='pilot',config={'provider':'anthropic','split':'development'},exploratory=True,rows=[])
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    write_summary(tmp_path)
    result=json.loads((tmp_path/'summary.json').read_text())
    assert result['exploratory'] is True
    assert result['findings_status']=='Exploratory pilot: labels and reports unreviewed; not benchmark findings'
