import math
import random
import statistics


def fraction(numerator, denominator, pending=0):
    return dict(numerator=numerator, denominator=denominator, pending=pending,
                value=numerator/denominator if denominator and not pending else None)


def primary(row):
    review = row.get('review') or {}
    return bool(row.get('valid') and review.get('correctness') == 2 and review.get('support') == 2
                and review.get('forbidden_overclaim') is False)


def abstains(row):
    return bool(row.get('valid') and row.get('status') == 'insufficient_evidence' and (row.get('review') or {}).get('abstention') is True)


def summarize(rows):
    answerable = [r for r in rows if r['answerability']=='answerable']
    insufficient = [r for r in rows if r['answerability']=='insufficient']
    # Operational failures count as misses even without a human review. Valid unreviewed reports stay pending.
    pending = lambda items: sum(r.get('valid',False) and r.get('review') is None for r in items)
    reviewed = [r for r in rows if r.get('review') is not None]
    claims = [c for r in reviewed for c in r['review'].get('claims',[])]
    bad = ('unsupported','contradicted','unjudgeable')
    factual = [r for r in reviewed if r['review'].get('claims')]
    latency = sorted(r.get('usage',{}).get('elapsed_ms',0) for r in rows)
    useful = sum(primary(r) if r['answerability']=='answerable' else abstains(r) for r in rows)
    costs = [r.get('usage',{}).get('estimated_cost_usd',0) for r in rows]
    faults = [r for r in rows if r.get('fault_scheduled')]
    fault_answerable = [r for r in faults if r['answerability']=='answerable']
    return dict(scheduled_runs=len(rows),
        outcomes={'diagnosis':sum(r.get('status')=='diagnosis' for r in rows),
                  'abstention':sum(r.get('status')=='insufficient_evidence' for r in rows),
                  'operational_fallback':sum(r.get('valid') and r.get('status')=='error' for r in rows),
                  'invalid_or_failed':sum(not r.get('valid') for r in rows)},
        supported_diagnosis=fraction(sum(primary(r) for r in answerable),len(answerable),pending(answerable)),
        appropriate_abstention=fraction(sum(abstains(r) for r in insufficient),len(insufficient),pending(insufficient)),
        over_abstention=fraction(sum(r.get('status')=='insufficient_evidence' for r in answerable),len(answerable)),
        valid_completion=fraction(sum(r.get('valid',False) for r in rows),len(rows)),
        useful_outcome=fraction(useful,len(rows),pending(rows)),
        claim_support=fraction(claims.count('supported'),len(claims),pending(rows)),
        unsupported_claims=fraction(sum(c in bad for c in claims),len(claims),pending(rows)),
        contradicted_claims=fraction(claims.count('contradicted'),len(claims),pending(rows)),
        reports_with_unsupported=fraction(sum(any(c in bad for c in r['review']['claims']) for r in factual),len(factual),pending(rows)),
        macro_report_support=statistics.mean([r['review']['claims'].count('supported')/len(r['review']['claims']) for r in factual]) if factual and not pending(rows) else None,
        zero_claim_reports=sum(not r['review'].get('claims') for r in reviewed),
        error_handling=fraction(sum(r.get('valid',False) for r in faults),len(faults)),
        tool_error_recovery=fraction(sum(primary(r) for r in fault_answerable),len(fault_answerable),pending(fault_answerable)),
        latency_ms={'median':statistics.median(latency) if latency else None,'p90':latency[math.ceil(.9*len(latency))-1] if latency else None,
                    'timeouts':sum('timeout' in r.get('termination_reason','') or r.get('termination_reason')=='deadline' for r in rows)},
        completed_latency_ms=[r.get('usage',{}).get('elapsed_ms') for r in rows if r.get('valid')],
        total_cost_usd=sum(costs), mean_cost_usd=statistics.mean(costs) if costs else None,
        cost_per_useful_outcome=sum(costs)/useful if useful and not pending(rows) else None,
        total_input_tokens=sum(r.get('usage',{}).get('input_tokens',0) for r in rows),
        total_output_tokens=sum(r.get('usage',{}).get('output_tokens',0) for r in rows),
        tool_dispatches=[r.get('usage',{}).get('tool_dispatches',0) for r in rows],
        unknown_usage_reservations=[v for r in rows for v in r.get('usage',{}).get('unknown_usage_reservations',[])])


def paired_bootstrap(rows, seed=17, repeats=2000):
    groups = {}
    for row in rows:
        groups.setdefault(row['group'],{}).setdefault(row['workflow'],[]).append(row['score'])
    differences = [statistics.mean(g['adaptive'])-statistics.mean(g['fixed']) for g in groups.values()
                   if g.get('adaptive') and g.get('fixed') and None not in g['adaptive']+g['fixed']]
    if not differences or len(differences)!=len(groups):
        return {'difference':None,'interval':None,'groups':len(groups)}
    rng=random.Random(seed)
    draws=sorted(statistics.mean(rng.choices(differences,k=len(differences))) for _ in range(repeats))
    return {'difference':statistics.mean(differences),'interval':[draws[int(.025*repeats)],draws[int(.975*repeats)]],
            'groups':len(groups),'limitation':'Exploratory capture-group bootstrap; few independent groups.'}
