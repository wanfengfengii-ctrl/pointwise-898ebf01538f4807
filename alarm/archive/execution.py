from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
from alarm.archive.tasks import load_task_snapshot
from alarm.archive.reports import assemble_report, assemble_interval_report, publish_report
from alarm.evidence.timeline import build_evidence_plan
from alarm.evidence.propagation import propagate_evidence, ImpossibleEvidence
from alarm.evidence.posteriors import smooth_posteriors
from alarm.evidence.interval_plan import build_interval_plan
from alarm.evidence.interval import propagate_interval, smooth_interval_posteriors
from alarm.occupancy.joint import conditional_occupancy
from alarm.occupancy.interval_joint import conditional_interval_occupancy
from alarm.occupancy.numerics import required_precision


class AnalysisExecutionError(ArithmeticError):
    pass


def _run_exact(snapshot, task_id):
    plan = build_evidence_plan(snapshot)
    evidence = propagate_evidence(plan)
    posteriors = smooth_posteriors(evidence, snapshot.queries)
    occupancy = conditional_occupancy(evidence, snapshot.axes)
    return assemble_report(task_id, snapshot, evidence, posteriors, occupancy)


def _run_interval(snapshot, task_id):
    plan = build_interval_plan(snapshot, snapshot.queries, snapshot.axes)
    messages, log_likelihood = propagate_interval(plan)
    supported_orderings = tuple(message.ordering for message in messages)
    posteriors = smooth_interval_posteriors(plan, messages)
    occupancy = conditional_interval_occupancy(
        plan, supported_orderings, snapshot.axes)
    # Likelihood, posteriors and occupancy must share the same conditional
    # denominator; the two independent propagations must agree on the mass.
    if abs(occupancy.log_scale - log_likelihood) > Decimal('1e-20'):
        raise AnalysisExecutionError('interval evidence and occupancy mass disagree')
    return assemble_interval_report(
        task_id, snapshot, plan, log_likelihood, posteriors, occupancy)


def analyze_task(store, task_id, before_commit=None):
    snapshot = load_task_snapshot(store, task_id)
    old = store.connection.execute('SELECT report_id FROM reports WHERE task_id=?', (task_id,)).fetchone()
    if old:
        return old[0]
    values = snapshot.model.definition.numbers() + snapshot.queries + tuple(
        t for axis in snapshot.axes for t in (axis.start, axis.end))
    has_intervals = any(record.is_interval for record in snapshot.observations.records)
    try:
        with localcontext() as ctx:
            ctx.prec = required_precision(snapshot.T, values)
            if has_intervals:
                # Interval placement integrals compare completion-stage masses
                # that can differ by many orders of magnitude (the rare
                # 1e-300 intensity case).  Widen precision by the data's
                # dynamic range so structurally supported tiny positive
                # evidence is never rounded to zero.
                rates = [value for _, row in snapshot.model.definition.intensities
                         for value in row if value > 0]
                if rates:
                    dynamic = int(max(abs(rate.ln()) for rate in rates))
                    ctx.prec = max(ctx.prec, dynamic + 120)
            ctx.Emax = MAX_EMAX
            ctx.Emin = MIN_EMIN
            if has_intervals:
                report = _run_interval(snapshot, task_id)
            else:
                report = _run_exact(snapshot, task_id)
    except ImpossibleEvidence:
        raise
    except ArithmeticError as exc:
        raise AnalysisExecutionError(str(exc)) from exc
    return publish_report(store, report, before_commit)
