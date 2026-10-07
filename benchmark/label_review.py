"""Evaluator-only label review packets. Never infer or fill human judgments."""
import argparse
from datetime import date
import html
import json
from pathlib import Path
from .dataset import audit_labels
from investigator.evidence import digest

CHECKS=('answerability','diagnostic_level','required_evidence','forbidden_claims','abstention','next_checks','coverage_and_counterevidence')


def load(root,split):
    labels=json.loads((root/'private/labels.json').read_text())
    audit_labels(labels)
    selected=[label for label in labels if label['split']==split]
    if not selected: raise ValueError('Empty review split')
    cases={}
    for label in selected:
        case=json.loads((root/'public'/f"{label['case_id']}.json").read_text())
        if digest(case['telemetry_snapshot'])!=label['snapshot_hash']:
            raise ValueError('Snapshot changed; regenerate review after correcting labels')
        cases[label['case_id']]=case
    return labels,selected,cases


def export_packets(root,split):
    root=Path(root)
    _,selected,cases=load(root,split)
    return dict(version='label-review-v1',split=split,label_hash=digest(selected),cases=[dict(
        case_id=label['case_id'],case_hash=digest(cases[label['case_id']]),label=label,
        reviewer=None,reviewed_at=None,notes='',checks={key:None for key in CHECKS}) for label in selected])


def validate_rows(packet,selected,cases):
    if packet.get('version')!='label-review-v1': raise ValueError('Unknown review version')
    if packet.get('label_hash')!=digest(selected): raise ValueError('Labels changed since export')
    rows=packet.get('cases',[])
    ids=[row['case_id'] for row in rows]
    if len(ids)!=len(selected) or set(ids)!={label['case_id'] for label in selected}:
        raise ValueError('Review every case exactly once')
    by_id={label['case_id']:label for label in selected}
    for row in rows:
        if row.get('case_hash')!=digest(cases[row['case_id']]) or row.get('label')!=by_id[row['case_id']]:
            raise ValueError('Case or label changed since export')
        if not isinstance(row.get('reviewer'),str) or not row['reviewer'].strip() or not isinstance(row.get('notes'),str) or not row['notes'].strip():
            raise ValueError('Identified human reviewer and review notes required')
        try: date.fromisoformat(row['reviewed_at'])
        except (ValueError,TypeError,KeyError): raise ValueError('Human review date must be YYYY-MM-DD')
        if set(row.get('checks',{}))!=set(CHECKS) or any(row['checks'][key] is not True for key in CHECKS):
            raise ValueError('Every human check must pass; correct disputed labels and export again')


def atomic_json(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,indent=2),encoding='utf-8')
    temporary.replace(path)


def import_audit(root,packet):
    root=Path(root)
    labels,selected,cases=load(root,packet['split'])
    validate_rows(packet,selected,cases)
    reviews={row['case_id']:row for row in packet['cases']}
    for label in selected:
        row=reviews[label['case_id']]
        label.update(review_status='audited',reviewer=row['reviewer'],reviewed_at=row['reviewed_at'],audit_notes=row['notes'])
    # Save the complete attestation before updating labels. A partial write fails closed.
    freeze=dict(version='label-review-freeze-v1',label_hash=digest(selected),
                case_hashes={key:digest(value) for key,value in cases.items()},review=packet)
    atomic_json(root/'private'/f"reviewed-{packet['split']}.json",freeze)
    atomic_json(root/'private/labels.json',labels)


def verify_audit(root,split):
    root=Path(root)
    _,selected,cases=load(root,split)
    path=root/'private'/f'reviewed-{split}.json'
    if not path.exists(): raise ValueError('Complete the human label audit and import its reviewed freeze first')
    freeze=json.loads(path.read_text())
    if freeze['label_hash']!=digest(selected) or freeze['case_hashes']!={key:digest(value) for key,value in cases.items()}:
        raise ValueError('Audited labels or cases changed; repeat human review')
    if any(label.get('review_status')!='audited' for label in selected): raise ValueError('Human audit incomplete')
    # Revalidate the retained original human attestation, not only status strings.
    if freeze.get('version')!='label-review-freeze-v1' or freeze['review'].get('split')!=split:
        raise ValueError('Review attestation split/version mismatch')
    rows=freeze['review']['cases']
    current={label['case_id']:label for label in selected}
    if len(rows)!=len(current) or {row['case_id'] for row in rows}!=set(current):
        raise ValueError('Review attestation must cover the frozen split exactly once')
    for row in rows:
        expected=dict(row['label'],review_status='audited',reviewer=row['reviewer'],
                      reviewed_at=row['reviewed_at'],audit_notes=row['notes'])
        if expected!=current[row['case_id']]:
            raise ValueError('Review attestation does not match frozen labels')
    original=[row['label'] for row in rows]
    validate_rows(freeze['review'],original,cases)


def write_guide(root,packet,path):
    _,_,cases=load(root,packet['split'])
    sections=[]
    for index,row in enumerate(packet['cases'],1):
        label=row['label']; case=cases[row['case_id']]
        sections.append(f'<section><h2>{index}. {html.escape(label["family"])} / {html.escape(label["answerability"])}</h2><p>Case: {row["case_id"]}</p><h3>Label to verify</h3><pre>{html.escape(json.dumps(label,indent=2))}</pre><details><summary>Open full exposed replay (alert, logs, metrics, changes and runbooks)</summary><pre>{html.escape(json.dumps(case,indent=2))}</pre></details></section>')
    path.write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Development label audit</title><style>body{max-width:1000px;margin:40px auto;padding:24px;font:16px/1.6 system-ui;background:#faf9f6;color:#141413}section{border-top:1px solid #aaa;margin-top:32px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#eeede7;padding:20px}summary{cursor:pointer;padding:16px;border:1px solid #aaa}</style><h1>Human label audit</h1><p>Evaluator-only material. Do not provide this page to the investigator. Check the exposed incident-window observations before accepting the hidden injected cause. Mark each check in the accompanying JSON, with your name, date and reasoning. Do not approve disputed labels: correct them and regenerate the packet. This page contains no model outputs.</p>'+''.join(sections)+'</html>',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('benchmark'))
    parser.add_argument('--split',choices=['development','held_out'],default='development')
    parser.add_argument('--import-audit',type=Path)
    args=parser.parse_args()
    if args.import_audit:
        import_audit(args.root,json.loads(args.import_audit.read_text(encoding='utf-8-sig')))
        print('Human audit imported and frozen.')
    else:
        packet=export_packets(args.root,args.split)
        folder=args.root/'private'
        path=folder/f'label-review-{args.split}.json'
        if path.exists(): raise ValueError('Review packet already exists; preserve any human work before regenerating')
        atomic_json(path,packet)
        write_guide(args.root,packet,path.with_suffix('.html'))
        print(f'Prepared {len(packet["cases"])} cases for human review: {path}')


if __name__=='__main__': main()
