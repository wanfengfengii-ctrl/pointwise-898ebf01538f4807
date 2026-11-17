import json
from decimal import Decimal
from alarm.models.types import ModelDefinition, decimal_text


def canonical_model_payload(model):
    return {'states': list(model.states),
            'Q': [[decimal_text(v) for v in row] for row in model.Q],
            'initial': [decimal_text(v) for v in model.initial],
            'intensities': {k: [decimal_text(v) for v in row]
                            for k, row in model.intensities}}


def encode_model_definition(model):
    return json.dumps(canonical_model_payload(model), sort_keys=True,
                      separators=(',', ':'), ensure_ascii=False)


def decode_model_definition(payload):
    value = json.loads(payload)
    return ModelDefinition(tuple(value['states']),
                           tuple(tuple(Decimal(x) for x in row) for row in value['Q']),
                           tuple(Decimal(x) for x in value['initial']),
                           tuple((k, tuple(Decimal(x) for x in row))
                                 for k, row in sorted(value['intensities'].items())))


def same_model_request(encoded, model):
    return decode_model_definition(encoded) == model
