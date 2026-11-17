import argparse
import json
import tempfile
from decimal import Decimal
from pathlib import Path
from alarm.archive.storage import ArchiveStore
from alarm.models.repository import register_model
from alarm.observations.batches import apply_observations
from alarm.archive.tasks import create_task
from alarm.archive.execution import analyze_task
from alarm.archive.reports import read_report, encode_report


def demonstrate(directory):
    data_path = Path(__file__).with_name('device_case.json')
    case = json.loads(data_path.read_text(encoding='utf-8'), parse_float=Decimal)
    path = Path(directory) / 'archive.sqlite'
    definition = {key: case[key] for key in ['states', 'Q', 'initial', 'intensities']}
    with ArchiveStore.open(path) as store:
        model = register_model(store, 'pump', 'survey-1', **definition)
        observations = apply_observations(store, 'pump-alarms', case['alarms'])
        old_task = create_task(store, 'pump', model.revision, 'pump-alarms', observations.revision,
                               case['T'], case['queries'], case['windows'])
        corrected = apply_observations(store, 'pump-alarms', [
            {'alarm_id': 'a-1', 'source_revision': 2, 'action': 'put',
             'time': Decimal('0.6'), 'kind': 'a'}])
        changed_definition = dict(definition)
        changed_definition['intensities'] = {'a': [Decimal('0.4'), Decimal('1.2')],
                                             'b': [Decimal('0.8'), Decimal('0.2')]}
        new_model = register_model(store, 'pump', 'survey-2', **changed_definition)
        new_task = create_task(store, 'pump', new_model.revision, 'pump-alarms', corrected.revision,
                               case['T'], case['queries'], case['windows'])
    with ArchiveStore.open(path) as store:
        old_id = analyze_task(store, old_task)
        def interrupt():
            raise RuntimeError('demonstration interruption before commit')
        try:
            analyze_task(store, new_task, before_commit=interrupt)
        except RuntimeError:
            pass
        else:
            raise AssertionError('publication interruption was not reached')
        if store.connection.execute('SELECT COUNT(*) FROM reports').fetchone()[0] != 1:
            raise AssertionError('failed publication became visible')
        old_report = read_report(store, old_id)
    with ArchiveStore.open(path) as store:
        new_id = analyze_task(store, new_task)
        if analyze_task(store, new_task) != new_id:
            raise AssertionError('successful retry was not idempotent')
        if read_report(store, old_id) != old_report:
            raise AssertionError('historical report changed')
        print(json.dumps({'archive': path.name, 'old_report': json.loads(encode_report(old_report)),
                          'new_report': json.loads(encode_report(read_report(store, new_id)))},
                         ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Run the device alarm archive example')
    parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='device-alarm-') as directory:
        demonstrate(directory)


if __name__ == '__main__':
    main()
