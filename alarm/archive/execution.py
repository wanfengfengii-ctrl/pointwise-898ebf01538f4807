from decimal import localcontext, MAX_EMAX, MIN_EMIN
from alarm.archive.tasks import load_task_snapshot
from alarm.archive.reports import assemble_report, publish_report
from alarm.evidence.timeline import build_evidence_plan
from alarm.evidence.propagation import propagate_evidence, ImpossibleEvidence
from alarm.evidence.posteriors import smooth_posteriors
from alarm.occupancy.joint import conditional_occupancy
from alarm.occupancy.numerics import required_precision


class AnalysisExecutionError(ArithmeticError):
    pass


def analyze_task(store, task_id, before_commit=None):
    snapshot = load_task_snapshot(store, task_id)
    old = store.connection.execute('SELECT report_id FROM reports WHERE task_id=?', (task_id,)).fetchone()
    if old:
        return old[0]
    values = snapshot.model.definition.numbers() + snapshot.queries + tuple(
        t for axis in snapshot.axes for t in (axis.start, axis.end))
    try:
        with localcontext() as ctx:
            ctx.prec = required_precision(snapshot.T, values)
            ctx.Emax = MAX_EMAX
            ctx.Emin = MIN_EMIN
            plan = build_evidence_plan(snapshot)
            evidence = propagate_evidence(plan)
            posteriors = smooth_posteriors(evidence, snapshot.queries)
            occupancy = conditional_occupancy(evidence, snapshot.axes)
            report = assemble_report(task_id, snapshot, evidence, posteriors, occupancy)
    except ImpossibleEvidence:
        raise
    except ArithmeticError as exc:
        raise AnalysisExecutionError(str(exc)) from exc
    return publish_report(store, report, before_commit)
