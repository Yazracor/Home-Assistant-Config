"""Garage warning regressions in HA's real template and script environment.

Run with the same image as devscripts/configcheck.sh, network disabled:
docker run --rm --network none -v "$PWD:/config:ro" \
  ghcr.io/home-assistant/home-assistant:stable \
  python /config/tools/tests/test_garage_drying.py
No live integrations, notifications or devices are contacted.
"""
import asyncio
import csv
import shutil
import tempfile
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.script import Script, async_validate_actions_config
from homeassistant.helpers.template import Template, async_load_custom_templates
from homeassistant.util import dt as dt_util


async def main():
    with tempfile.TemporaryDirectory(prefix="garage-drying-test-") as folder:
        shutil.copytree('/config/custom_templates', folder + '/custom_templates')
        runtime = HomeAssistant(folder)
        await async_load_custom_templates(runtime)
        render = lambda text, **variables: Template(text, runtime).async_render(variables)
        snapshot_template = """{% from 'garage_drying.jinja' import drying_snapshot %}
          {{ (drying_snapshot | as_function)(previous, reset, timestamp, humidity, ttk, ttr) }}"""
        epoch = dt_util.utcnow()

        def tick(previous, minute, humidity=62, ttk='on', ttr='off', reset=False):
            return render(snapshot_template, previous=previous, reset=reset,
                          timestamp=(epoch + timedelta(minutes=minute)).timestamp(),
                          humidity=humidity, ttk=ttk, ttr=ttr)

        # An already-running socket never supplies elapsed high-humidity time.
        state = {}
        for minute in range(181):
            state = tick(state, minute)
            assert state['drying_warning'] == (minute == 180), (minute, state)
        assert not state['boost_warning']

        # A successful drop from a peak counts even if the phase began near 60%.
        state = {}
        for minute in range(181):
            humidity = 60.1 if minute < 30 else 65 if minute < 90 else 61.5
            state = tick(state, minute, humidity)
        assert not state['drying_warning'], state
        assert state['reference_humidity'] == 65
        # Old success cannot hide a subsequent three-hour plateau indefinitely.
        for minute in range(181, 272):
            state = tick(state, minute, 61.5)
        assert state['drying_warning'], state
        assert len(state['samples']) <= 182

        # Exact 3-point improvement is enough; exact 1-point rise warns.
        state = {}
        for minute in range(181):
            state = tick(state, minute, 64.3 if minute < 120 else 61.3)
        assert not state['drying_warning']

        # The last hour is compared, not a stale boost-start value. A previous
        # successful hour cannot suppress a newly rising hour or extend it 1m.
        state = {}
        for minute in range(121):
            humidity = 63 if minute < 60 else 61.3 if minute < 120 else 62.3
            state = tick(state, minute, humidity, ttr='on')
        assert state['boost_warning'], state
        assert state['boost_reference_humidity'] == 61.3
        state = tick(state, 121, 61.3, ttr='on')
        assert not state['boost_warning'], state
        state = {}
        for minute in range(61):
            state = tick(state, minute, 61.3 if minute < 60 else 62.3, ttr='on')
            assert state['boost_warning'] == (minute == 60), (minute, state)
        assert not state['drying_warning']

        # Stopping TTR or dipping to 60% invalidates the boost's elapsed hour.
        stopped = tick(state, 61, 62.3, ttr='off')
        assert stopped['boost_samples'] == [] and stopped['boost_since'] is None
        restarted = tick(stopped, 62, 62.3, ttr='on')
        assert not restarted['boost_warning']
        dipped = tick(state, 61, 60, ttr='on')
        assert dipped['samples'] == dipped['boost_samples'] == []
        assert not tick(dipped, 62, 62.3, ttr='on')['boost_warning']

        # Recovery requires the full 45 minutes, including the exact 58% edge.
        state = tick({}, 0, 58, ttr='on')
        for minute in range(1, 46):
            state = tick(state, minute, 58, ttr='on')
            assert state['recovered'] == (minute == 45), (minute, state)
        recovered = state
        # Regression for the reported recovery -> warning after only 18 minutes.
        for minute in range(46, 65):
            state = tick(state, minute, 60.1, ttr='on')
            assert not state['drying_warning'] and not state['boost_warning']
        assert state['high_since'] > recovered['low_since']
        interrupted = tick(recovered, 46, 58.1)
        assert not interrupted['recovered'] and interrupted['low_since'] is None
        assert not tick(interrupted, 47, 58)['recovered']

        # Unavailable input, all devices off, restart and sampling gaps never
        # turn old elapsed time into proof of current drying failure.
        state = {}
        for minute in range(181):
            state = tick(state, minute, 62, ttr='on')
        assert state['drying_warning']
        for humidity, ttk, ttr in [('unavailable', 'on', 'on'),
                                   (62, 'off', 'off'), (62, 'unknown', 'on')]:
            invalid = tick(state, 181, humidity, ttk, ttr)
            assert not invalid['drying_warning'] and invalid['samples'] == []
            assert not tick(invalid, 182, 62, ttr='on')['drying_warning']
        assert not tick(state, 181, 62, ttr='on', reset=True)['drying_warning']
        assert not tick(state, 184, 62, ttr='on')['drying_warning']

        package = yaml.safe_load(open('/config/virtual/garage_drying.yaml'))
        automations = {a['id']: a for a in yaml.safe_load(open('/config/automations.yaml'))}
        block = package['template'][0]
        observer = block['sensor'][0]
        observer_id = observer['default_entity_id']
        runtime.states.async_set('switch.entfeuchter', 'on')
        runtime.states.async_set('switch.ttr_57_entfeuchter', 'on')
        runtime.states.async_set('sensor.wifi_smart_switch_humidity', '62')
        runtime.states.async_set('sensor.wifi_smart_switch_temperature', '13')

        # Run the real trigger-template action repeatedly without injected this.
        actions = Script(runtime, await async_validate_actions_config(
            runtime, cv.SCRIPT_SCHEMA(block['actions'])), 'Garage observer test', 'template')
        for minute in range(181):
            with patch('homeassistant.util.dt.now', return_value=epoch + timedelta(minutes=minute)):
                result = await actions.async_run({'trigger': SimpleNamespace(id='sample')}, Context())
            drying = result.variables['drying']
            attributes = {key: render(value, drying=drying)
                          for key, value in observer['attributes'].items()}
            runtime.states.async_set(observer_id, str(minute), attributes)
            assert attributes['drying_warning'] == (minute == 180)
        assert observer_id in package['recorder']['exclude']['entities']

        # Real configured conditions/actions: independent warning latches,
        # exactly one notification per type, one joint recovery, no short rearm.
        notices = []

        async def notify(call):
            notices.append(call.data)

        async def set_boolean(call):
            entity_ids = call.data['entity_id']
            if isinstance(entity_ids, str):
                entity_ids = [entity_ids]
            for entity_id in entity_ids:
                runtime.states.async_set(entity_id, 'on' if call.service == 'turn_on' else 'off')

        runtime.services.async_register('notify', 'mobile_app_torbens_iphone', notify)
        runtime.services.async_register('input_boolean', 'turn_on', set_boolean)
        runtime.services.async_register('input_boolean', 'turn_off', set_boolean)
        runtime.services.async_register('switch', 'turn_on', set_boolean)
        runtime.services.async_register('switch', 'turn_off', set_boolean)
        general = 'input_boolean.garage_entfeuchtung_warnung_aktiv'
        boost = 'input_boolean.garage_entfeuchtung_boost_warnung_aktiv'
        for entity_id in (general, boost):
            runtime.states.async_set(entity_id, 'off')

        async def run_automation(aid):
            config = automations[aid]
            sequence = config['conditions'] + config['actions']
            script = Script(runtime, await async_validate_actions_config(
                runtime, cv.SCRIPT_SCHEMA(sequence)), aid, 'automation')
            await script.async_run({}, Context())

        warn_id = 'garage_entfeuchter_trocknet_nicht_genug'
        boost_id = 'garage_entfeuchter_beide_feuchte_steigt_warnung'
        ok_id = 'garage_entfeuchter_feuchte_wieder_ok'
        runtime.states.async_set(observer_id, 'warn', {
            'drying_warning': True, 'boost_warning': True,
            'reference_humidity': 62, 'boost_reference_humidity': 61})
        for _ in range(2):
            await run_automation(warn_id)
            await run_automation(boost_id)
        assert len(notices) == 2, notices
        assert runtime.states.is_state(general, 'on') and runtime.states.is_state(boost, 'on')
        runtime.states.async_set(observer_id, 'recovered', {'recovered': True})
        for _ in range(2):
            await run_automation(ok_id)
        assert len(notices) == 3, notices
        assert runtime.states.is_state(general, 'off') and runtime.states.is_state(boost, 'off')
        runtime.states.async_set(observer_id, 'short-rebound', {
            'drying_warning': False, 'boost_warning': False})
        await run_automation(warn_id)
        await run_automation(boost_id)
        assert len(notices) == 3

        # Inclusive shutdown target and exact time conditions from the YAML.
        low_sensor = next(e for b in package['template'] for e in b.get('binary_sensor', [])
                          if e['unique_id'] == 'garage_feuchte_unter_58')
        runtime.states.async_set('sensor.wifi_smart_switch_humidity', '58')
        assert render(low_sensor['state'])
        runtime.states.async_set('sensor.wifi_smart_switch_humidity', '58.1')
        assert not render(low_sensor['state'])
        runtime.states.async_set('sensor.wifi_smart_switch_humidity', 'unavailable')
        assert not render(low_sensor['availability'])
        on = automations['garage_ttr_entfeuchter_boost_an']
        off = automations['garage_ttr_entfeuchter_boost_aus']
        assert off['conditions'][1]['entity_id'] == low_sensor['default_entity_id']
        # Exercise the actual duration guards: regular boost after 30 minutes,
        # even when TTK was not on for 45 minutes; shutdown only after 45 low.
        for entity_id, value in [
            ('switch.entfeuchter', 'on'), ('switch.ttr_57_entfeuchter', 'off'),
            ('binary_sensor.garage_feuchte_ueber_60', 'on'),
            ('binary_sensor.garage_ttk_leistung_unter_100', 'off'),
            ('binary_sensor.garage_temperatur_unter_5', 'off'),
        ]:
            runtime.states.async_set(entity_id, value, timestamp=epoch.timestamp())
        for minute in (29, 30):
            with patch('homeassistant.util.dt.utcnow', return_value=epoch + timedelta(minutes=minute, seconds=1)):
                await run_automation(on['id'])
            assert runtime.states.is_state('switch.ttr_57_entfeuchter', 'on' if minute == 30 else 'off')
        runtime.states.async_set(low_sensor['default_entity_id'], 'on',
                                 timestamp=(epoch + timedelta(minutes=31)).timestamp())
        for minute in (75, 76):
            with patch('homeassistant.util.dt.utcnow', return_value=epoch + timedelta(minutes=minute, seconds=1)):
                await run_automation(off['id'])
            assert runtime.states.is_state('switch.ttr_57_entfeuchter', 'off' if minute == 76 else 'on')

        # Existing identities are durable, including the renamed <=58 display.
        with open('/config/area_assignments.csv', newline='') as stream:
            assignments = list(csv.DictReader(stream))
        by_entity = {row['expected_entity_id']: row for row in assignments}
        assert len(by_entity) == len(assignments)
        identified = [r for r in assignments if r['unique_id']]
        assert len({(r['domain'], r['unique_id']) for r in identified}) == len(identified)
        for entity in (observer, low_sensor,
                       next(e for b in package['template'] for e in b.get('binary_sensor', [])
                            if e['unique_id'] == 'garage_feuchte_ueber_60')):
            row = next(r for r in assignments if r['unique_id'] == entity['unique_id'])
            assert row['name'] == entity['name'] and row['area_id'] == 'garage'
        for aid in ('garage_ttr_entfeuchter_boost_an', 'garage_ttr_entfeuchter_boost_aus',
                    'garage_entfeuchter_startfeuchte_merker',
                    'garage_entfeuchter_boost_startfeuchte_merken', warn_id, boost_id, ok_id):
            row = next(r for r in assignments if r['domain'] == 'automation' and r['unique_id'] == aid)
            assert row['name'] == automations[aid]['alias'] and row['area_id'] == 'garage'
        # Four input booleans/numbers are internal helpers without area needs;
        # the unchanged whole-house digest deliberately has no garage assignment.
        print('Garage drying: time windows, peak progress, recovery/rebound, invalid input,')
        print('template state retention, independent notifications and CSV identity checks passed.')


asyncio.run(main())
