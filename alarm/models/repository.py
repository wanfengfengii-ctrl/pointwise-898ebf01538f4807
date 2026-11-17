from alarm.models.types import ModelRevision, ModelReceipt, identifier
from alarm.models.validation import validate_model
from alarm.models.revisions import encode_model_definition, decode_model_definition, same_model_request


class ModelRequestConflict(ValueError):
    pass


class ModelRevisionNotFound(LookupError):
    pass


def register_model(store, model_id, request_id, states, Q, initial, intensities):
    identifier(model_id)
    identifier(request_id)
    model = validate_model(states, Q, initial, intensities)
    payload = encode_model_definition(model)
    with store.transaction() as db:
        old = db.execute('SELECT revision, payload FROM model_requests WHERE model_id=? AND request_id=?',
                         (model_id, request_id)).fetchone()
        if old:
            if not same_model_request(old[1], model):
                raise ModelRequestConflict('request ID already names different model content')
            return ModelReceipt(model_id, old[0], request_id)
        revision = db.execute('SELECT COALESCE(MAX(revision),0)+1 FROM model_revisions WHERE model_id=?',
                              (model_id,)).fetchone()[0]
        db.execute('INSERT INTO model_revisions VALUES (?,?,?)', (model_id, revision, payload))
        db.execute('INSERT INTO model_requests VALUES (?,?,?,?)',
                   (model_id, request_id, revision, payload))
    return ModelReceipt(model_id, revision, request_id)


def get_model_revision(store, model_id, revision):
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ModelRevisionNotFound((model_id, revision))
    row = store.connection.execute('SELECT payload FROM model_revisions WHERE model_id=? AND revision=?',
                                   (model_id, revision)).fetchone()
    if row is None:
        raise ModelRevisionNotFound((model_id, revision))
    return ModelRevision(model_id, revision, decode_model_definition(row[0]))
