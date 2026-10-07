"""Public human claim review, independent of private benchmark scoring."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from .evidence import digest


def claim_inventory(report):
    """Inventory prose; classification and atomic splitting belong to the reviewer."""
    units=[]
    def visit(value,path):
        if isinstance(value,dict):
            for key,item in value.items():
                if key not in ('claim_id','type','status','diagnostic_level','evidence_ids','supporting_ids','contradicting_ids'):
                    visit(item,path+'/'+key)
        elif isinstance(value,list):
            for index,item in enumerate(value): visit(item,path+'/'+str(index))
        elif isinstance(value,str) and value:
            units.append(dict(unit_id=path,text=value,contains_no_factual_claims=None,atomic_claims=[]))
    visit(report,'report')
    return units


class AtomicClaim(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text: str = Field(max_length=4000)
    label: Literal['supported','unsupported','contradicted','unjudgeable'] | None = None
    evidence_ids: list[str] = Field(default_factory=list,max_length=100)
    notes: str = Field(default='',max_length=4000)


class ReviewUnit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    unit_id: str
    text: str
    contains_no_factual_claims: StrictBool | None = None
    atomic_claims: list[AtomicClaim] = Field(default_factory=list,max_length=100)


class ReviewSubmission(BaseModel):
    model_config=ConfigDict(extra='forbid')
    run_id: str | None = None
    coverage: dict | None = None
    stale_review: dict | None = None
    archived_reviews: list[dict] = Field(default_factory=list)
    revision: int = Field(ge=0,strict=True)
    report_hash: str
    evidence_hash: str
    status: Literal['draft','final'] = 'draft'
    reviewer: str | None = Field(default=None,max_length=200)
    complete_claim_review: StrictBool = False
    notes: str = Field(default='',max_length=20000)
    claim_units: list[ReviewUnit] = Field(max_length=1000)


class ReviewConflict(ValueError): pass


def unit_complete(unit):
    claims=unit['atomic_claims']
    return (unit['contains_no_factual_claims'] is True and not claims) or (
        unit['contains_no_factual_claims'] is False and bool(claims) and
        all(c['text'].strip() and c['label'] is not None for c in claims))


def coverage(review):
    units=review['claim_units']
    claims=[c for unit in units for c in unit['atomic_claims']]
    final=review['status']=='final'
    return dict(total_units=len(units),reviewed_units=sum(bool(unit_complete(u)) for u in units),
        total_claims=len(claims),judged_claims=sum(c['label'] is not None for c in claims),
        review_status='final' if final else 'draft' if review['revision'] else 'pending',
        **{label:sum(c['label']==label for c in claims) if final else None
           for label in ('supported','unsupported','contradicted','unjudgeable')})


class ReviewStore:
    def __init__(self,path): self.path=Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS reviews (run_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS review_revisions (run_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id,revision))')
                yield db
        finally:
            db.close()

    def get(self,run_id,result):
        with self.connect() as db:
            row=db.execute('SELECT revision,payload FROM reviews WHERE run_id=?',(run_id,)).fetchone()
            history=db.execute('SELECT payload FROM review_revisions WHERE run_id=? ORDER BY revision DESC',(run_id,)).fetchall()
        hashes=dict(report_hash=digest(result['report']),evidence_hash=digest(result['evidence']))
        saved=json.loads(row[1]) if row else None
        stale=None
        if saved and all(saved[k]==v for k,v in hashes.items()):
            review=saved
        else:
            stale=saved
            review=dict(run_id=run_id,revision=row[0] if row else 0,**hashes,status='draft',reviewer=None,
                complete_claim_review=False,notes='',claim_units=claim_inventory(result['report']))
        review['coverage']=coverage(review)
        if stale:
            review['coverage']['review_status']='pending'
        review['stale_review']=stale
        review['archived_reviews']=[item for raw in history if (item:=json.loads(raw[0]))['revision']!=review['revision']]
        return review

    def save(self,run_id,result,submission):
        review=submission.model_dump(exclude={'coverage','run_id','stale_review','archived_reviews'})
        if review['report_hash']!=digest(result['report']) or review['evidence_hash']!=digest(result['evidence']):
            raise ReviewConflict('Report or evidence changed; reload the review.')
        expected=claim_inventory(result['report'])
        units=review['claim_units']
        if len(units)!=len(expected) or {u['unit_id']:u['text'] for u in units}!={u['unit_id']:u['text'] for u in expected}:
            raise ValueError('Every original report text unit must appear exactly once, unchanged.')
        for unit in units:
            if unit['contains_no_factual_claims'] is True and unit['atomic_claims']:
                raise ValueError('A nonfactual unit cannot contain factual claims.')
            for claim in unit['atomic_claims']:
                if not set(claim['evidence_ids'])<=set(result['evidence']):
                    raise ValueError('Evidence references must belong to this run.')
                if claim['label'] in ('supported','contradicted') and not claim['evidence_ids']:
                    raise ValueError('Supported or contradicted judgments require evidence references.')
        if review['status']=='final' and (not (review['reviewer'] or '').strip() or
            review['complete_claim_review'] is not True or not all(unit_complete(u) for u in units)):
            raise ValueError('Final review requires a named reviewer, complete unit judgments and explicit completeness attestation.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT revision,payload FROM reviews WHERE run_id=?',(run_id,)).fetchone()
            if review['revision']!=(row[0] if row else 0):
                raise ReviewConflict('Review revision changed; reload before saving.')
            review.update(run_id=run_id,revision=review['revision']+1)
            if row:
                db.execute('INSERT OR IGNORE INTO review_revisions VALUES (?,?,?)',(run_id,row[0],row[1]))
            db.execute('INSERT INTO reviews VALUES (?,?,?) ON CONFLICT(run_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload',
                (run_id,review['revision'],json.dumps(review)))
        return self.get(run_id,result)
