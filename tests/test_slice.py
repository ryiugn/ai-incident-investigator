import json
import pytest
from pydantic import ValidationError


def test_fixed_slice_archives_cited_report(tmp_path):
    from investigator.demo import demo_case
    from investigator.runner import run_investigation
    from investigator.provider import ScriptedProvider
    import asyncio
    case = demo_case()
    result = asyncio.run(run_investigation(case, ScriptedProvider(), archive=tmp_path, minimal=True))
    assert result['report']['diagnostic_level'] == 'condition'
    assert result['usage']['tool_dispatches'] == 2
    assert result['usage']['model_requests'] == 1
    ids = result['report']['likely_cause']['evidence_ids']
    assert ids and all(i in result['evidence'] for i in ids)
    saved = json.loads((tmp_path / (result['run_id'] + '.json')).read_text())
    assert saved == result


def test_missing_decisive_evidence_abstains(tmp_path):
    from investigator.demo import demo_case
    from investigator.runner import run_investigation
    from investigator.provider import ScriptedProvider
    import asyncio
    case = demo_case(missing=True)
    result = asyncio.run(run_investigation(case, ScriptedProvider(), archive=tmp_path, minimal=True))
    assert result['report']['status'] == 'insufficient_evidence'
    assert result['report']['likely_cause'] is None


def test_time_window_rejects_naive_reversed_and_too_wide():
    from investigator.contracts import Window
    for start, end in [('2026-01-01T00:00:00', '2026-01-01T00:01:00Z'),
                       ('2026-01-01T00:02:00Z', '2026-01-01T00:01:00Z'),
                       ('2026-01-01T00:00:00Z', '2026-01-01T00:31:00Z')]:
        with pytest.raises(ValidationError):
            Window(start=start, end=end)


def test_unknown_and_unsupplied_citation_rejected():
    from investigator.evidence import validate_citations
    with pytest.raises(ValueError):
        validate_citations({'evidence_ids': ['ev-missing']}, {}, set())
    with pytest.raises(ValueError):
        validate_citations({'evidence_ids': ['ev-present']}, {'ev-present': {}}, set())
