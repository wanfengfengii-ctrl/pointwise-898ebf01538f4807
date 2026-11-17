SCHEMA_VERSION = 1
SCHEMA_STATEMENTS = (
    'CREATE TABLE IF NOT EXISTS model_revisions (model_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0), payload TEXT NOT NULL, PRIMARY KEY(model_id,revision))',
    'CREATE TABLE IF NOT EXISTS model_requests (model_id TEXT NOT NULL, request_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(model_id,request_id), FOREIGN KEY(model_id,revision) REFERENCES model_revisions(model_id,revision))',
    'CREATE TABLE IF NOT EXISTS observation_revisions (sequence_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0), payload TEXT NOT NULL, PRIMARY KEY(sequence_id,revision))',
    'CREATE TABLE IF NOT EXISTS source_history (sequence_id TEXT NOT NULL, alarm_id TEXT NOT NULL, source_revision INTEGER NOT NULL CHECK(source_revision>0), payload TEXT NOT NULL, PRIMARY KEY(sequence_id,alarm_id,source_revision))',
    "CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('READY','PUBLISHED')))",
    'CREATE TABLE IF NOT EXISTS reports (report_id TEXT PRIMARY KEY, task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id), payload TEXT NOT NULL)',
)


def initialize_schema(connection):
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version not in (0, SCHEMA_VERSION):
        raise ValueError('unsupported archive schema version')
    connection.execute('BEGIN IMMEDIATE')
    try:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute('PRAGMA user_version=1')
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
