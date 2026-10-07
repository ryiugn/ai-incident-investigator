import copy
import json
import pytest
from fastapi.testclient import TestClient
from investigator.api import create_app


def result(workflow='fixed'):
    return dict(run_id=workflow, workflow=workflow, provider='scripted', snapshot_hash='same',
        limits={'tools':4}, configuration={'provider':'scripted','limits':{'tools':4}}, alert_hash='same-alert', schema_version=1, report={'uncertainty':'Some uncertainty',
        'next_steps':[{'action':'Inspect logs','purpose':'Find cause','prerequisite':'Read access'}]},
        evidence={'ev1':{'payload':{'text':'sample'}}}, events=[], usage={})


def client(tmp_path, runs=None):
    archive=tmp_path/'archive'
    (archive/'jobs').mkdir(parents=True,exist_ok=True)
    for key, value in (runs or {'fixed':result()}).items():
        (archive/'jobs'/f'{key}.json').write_text(json.dumps(dict(run_id=key,state='finished',result=value)))
    return TestClient(create_app(archive=archive,public=tmp_path/'public',results=tmp_path/'results',ui=tmp_path/'ui'))


def test_draft_restart_and_conflicting_edit(tmp_path):
    with client(tmp_path) as c:
        response=c.get('/api/runs/fixed/review')
        assert response.status_code==200
        review=response.json()
        assert len(review['claim_units'])==4
        assert review['coverage']['supported'] is None
        review['notes']='Partially reviewed'
        saved=c.post('/api/runs/fixed/review',json=review)
        assert saved.status_code==200
        assert saved.json()['revision']==1
        assert c.post('/api/runs/fixed/review',json=review).status_code==409
    with client(tmp_path) as c:
        assert c.get('/api/runs/fixed/review').json()['notes']=='Partially reviewed'


def test_final_requires_complete_named_review_and_valid_binding(tmp_path):
    with client(tmp_path) as c:
        review=c.get('/api/runs/fixed/review').json()
        review.update(status='final',reviewer='Test fixture reviewer',complete_claim_review=True)
        assert c.post('/api/runs/fixed/review',json=review).status_code==422
        for unit in review['claim_units']: unit['contains_no_factual_claims']=True
        review['claim_units'][0].update(contains_no_factual_claims=False,atomic_claims=[dict(text='A claim',label='supported',evidence_ids=['bad'])])
        assert c.post('/api/runs/fixed/review',json=review).status_code==422
        review['claim_units'][0]['atomic_claims'][0]['evidence_ids']=['ev1']
        stale=copy.deepcopy(review); stale['evidence_hash']='stale'
        assert c.post('/api/runs/fixed/review',json=stale).status_code==409
        unnamed=copy.deepcopy(review); unnamed['reviewer']=' '
        assert c.post('/api/runs/fixed/review',json=unnamed).status_code==422
        saved=c.post('/api/runs/fixed/review',json=review)
        assert saved.status_code==200
        assert saved.json()['coverage']['supported']==1


def test_comparison_requires_matching_snapshot_and_config(tmp_path):
    left,right=result(),result('adaptive')
    with client(tmp_path,{'left':left,'right':right}) as c:
        response=c.get('/api/run-comparison?left=left&right=right')
        assert response.status_code==200
        comparison=response.json()
        assert comparison['paired'] is True
        assert comparison['left']['review_coverage']['review_status']=='pending'
        assert 'winner' not in comparison
    right['snapshot_hash']='different'
    right['provider']='different'
    with client(tmp_path,{'left':left,'right':right}) as c:
        comparison=c.get('/api/run-comparison?left=left&right=right').json()
        assert comparison['paired'] is False
        assert len(comparison['incompatibilities'])>=2


def test_inventory_includes_all_prose_without_structural_ids():
    from investigator.review import claim_inventory
    report={'status':'diagnosis','diagnostic_level':'condition','observed_symptoms':[
        {'claim_id':'c1','type':'observation','text':'Symptom','limitations':'Sparse sample','evidence_ids':['ev1']}],
        'alternatives':[{'description':'Other cause','unresolved_reason':'Need evidence','supporting_ids':['ev1'],'contradicting_ids':[]}],
        'missing_evidence':['Missing trace'],'uncertainty':'Uncertain','next_steps':[
            {'action':'Inspect','purpose':'Learn','prerequisite':'Access','evidence_ids':['ev1']}],
        'future_context':{'explanation':'Additional report prose'}}
    assert [u['text'] for u in claim_inventory(report)]==[
        'Symptom','Sparse sample','Other cause','Need evidence','Missing trace','Uncertain','Inspect','Learn','Access','Additional report prose']


def test_changed_content_invalidates_saved_review_and_old_write(tmp_path):
    with client(tmp_path) as c:
        review=c.get('/api/runs/fixed/review').json()
        review.update(status='final',reviewer='Test fixture reviewer',complete_claim_review=True)
        for unit in review['claim_units']: unit['contains_no_factual_claims']=True
        old=c.post('/api/runs/fixed/review',json=review).json()
    changed=result(); changed['evidence']['ev1']['payload']['text']='changed'
    with client(tmp_path,{'fixed':changed}) as c:
        fresh=c.get('/api/runs/fixed/review').json()
        assert fresh['coverage']['supported'] is None
        assert fresh['coverage']['review_status']=='pending'
        assert fresh['reviewer'] is None
        assert c.post('/api/runs/fixed/review',json=old).status_code==409
        assert c.post('/api/runs/fixed/review',json=fresh).status_code==200


@pytest.mark.parametrize('mutation', ['omit','duplicate','changed_text','missing_attestation','missing_label'])
def test_final_rejects_incomplete_and_tampered_inventory(tmp_path,mutation):
    with client(tmp_path) as c:
        review=c.get('/api/runs/fixed/review').json()
        review.update(status='final',reviewer='Test fixture reviewer',complete_claim_review=True)
        for unit in review['claim_units']: unit['contains_no_factual_claims']=True
        if mutation=='omit': review['claim_units'].pop()
        if mutation=='duplicate': review['claim_units'][1]=review['claim_units'][0]
        if mutation=='changed_text': review['claim_units'][0]['text']='Edited report'
        if mutation=='missing_attestation': review['complete_claim_review']=False
        if mutation=='missing_label': review['claim_units'][0].update(contains_no_factual_claims=False,atomic_claims=[dict(text='Claim',label=None,evidence_ids=[])])
        assert c.post('/api/runs/fixed/review',json=review).status_code==422


def test_stale_human_work_remains_readable_after_replacement(tmp_path):
    with client(tmp_path) as c:
        review=c.get('/api/runs/fixed/review').json()
        review['notes']='Original human notes'
        old=c.post('/api/runs/fixed/review',json=review).json()
    changed=result(); changed['report']['uncertainty']='Changed report'
    with client(tmp_path,{'fixed':changed}) as c:
        fresh=c.get('/api/runs/fixed/review').json()
        assert fresh['stale_review']['notes']=='Original human notes'
        fresh['notes']='New report review'
        assert c.post('/api/runs/fixed/review',json=fresh).status_code==200
    with client(tmp_path,{'fixed':changed}) as c:
        fresh=c.get('/api/runs/fixed/review').json()
        assert fresh['notes']=='New report review'
        assert any(r['notes']=='Original human notes' for r in fresh['archived_reviews'])


def test_canonical_snapshot_binding_allows_raw_format_difference(tmp_path):
    left,right=result(),result('adaptive')
    left.update(snapshot_hash='raw-left',frozen_snapshot_hash='canonical')
    right.update(snapshot_hash='raw-right',frozen_snapshot_hash='canonical')
    with client(tmp_path,{'left':left,'right':right}) as c:
        assert c.get('/api/run-comparison?left=left&right=right').json()['paired'] is True

def test_public_api_ignores_private_case_metadata_and_provider_credentials(tmp_path):
    import time
    from investigator.demo import demo_case
    from investigator.provider import ScriptedProvider
    public=tmp_path/'public';public.mkdir()
    case=demo_case();case['opaque_case_id']='sanitized-case'
    case.update(private_label='PRIVATE_LABEL_SENTINEL',credentials='CREDENTIAL_SENTINEL')
    (public/'case.json').write_text(json.dumps(case))
    provider=ScriptedProvider();provider.secret='PROVIDER_SECRET_SENTINEL'
    with TestClient(create_app(archive=tmp_path/'archive',public=public,results=tmp_path/'results',provider=provider)) as c:
        run=c.post('/api/runs',json={'case_id':'sanitized-case','workflow':'adaptive'}).json()['run_id']
        for _ in range(100):
            job=c.get('/api/runs/'+run).json()
            if job['state']=='finished':break
            time.sleep(.02)
        assert job['state']=='finished'
        bodies=[job,c.get('/api/runs/'+run+'/review').json(),c.get('/api/run-comparison',params={'left':run,'right':run}).json(),c.get('/api/cases').json()]
        assert all(secret not in json.dumps(bodies) for secret in ('PRIVATE_LABEL_SENTINEL','CREDENTIAL_SENTINEL','PROVIDER_SECRET_SENTINEL'))
