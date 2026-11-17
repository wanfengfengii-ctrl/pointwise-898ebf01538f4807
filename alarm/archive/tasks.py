from uuid import uuid4
from alarm.archive.snapshots import freeze_task_inputs, encode_task_snapshot, decode_task_snapshot


class TaskNotFound(LookupError):
    pass


def create_task(store, model_id, model_revision, sequence_id, observation_revision,
                T, queries=(), windows=()):
    with store.transaction() as db:
        snapshot = freeze_task_inputs(store, model_id, model_revision, sequence_id,
                                      observation_revision, T, queries, windows)
        task_id = uuid4().hex
        db.execute("INSERT INTO tasks VALUES (?,?,'READY')", (task_id, encode_task_snapshot(snapshot)))
    return task_id


def load_task_snapshot(store, task_id):
    row = store.connection.execute('SELECT snapshot FROM tasks WHERE task_id=?', (task_id,)).fetchone()
    if row is None:
        raise TaskNotFound(task_id)
    return decode_task_snapshot(row[0])
