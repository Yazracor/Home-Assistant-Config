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

        # Power monitoring must exempt only the observed eight-hour cycle,
        # while retaining ten-minute warnings for other failures.
        power_template = """{% from 'garage_ttr_power.jinja' import ttr_power_snapshot %}
          {{ (ttr_power_snapshot | as_function)(previous, reset, timestamp, switch, power) }}"""

        def power_tick(previous, minute, watts=710, switch='on', reset=False):
            return render(power_template, previous=previous, reset=reset,
                          timestamp=(epoch + timedelta(minutes=minute)).timestamp(),
                          switch=switch, power=watts)

        idle = {}
        for minute in range(11):
            idle = power_tick(idle, minute, 0)
            assert idle['warning'] == (minute == 10)
            assert not idle['scheduled_pause']  # An on socket proves no runtime.

        operating = {}
        for minute in range(480):
            operating = power_tick(operating, minute)
            assert not operating['warning']
            if minute == 119:
                early = operating
        for minute in range(120, 131):
            early = power_tick(early, minute, 0)
            assert early['warning'] == (minute == 130)
            assert not early['scheduled_pause']

        paused = power_tick(operating, 480, 0)
        assert paused['scheduled_pause'] and not paused['warning']
        for minute in range(481, 513):
            paused = power_tick(paused, minute, 0)
            assert paused['warning'] == (minute == 512), (minute, paused)
            if minute == 509:
                before_restart = paused
        # Resumption after the regular 30-minute pause begins a fresh cycle.
        resumed = power_tick(before_restart, 510, 71)
        assert resumed['low_since'] is None and resumed['pause_until'] is None
        assert resumed['running_since'] == (epoch + timedelta(minutes=510)).timestamp()
        for minute in range(511, 990):
            resumed = power_tick(resumed, minute)
        second_pause = power_tick(resumed, 990, 0)
        assert second_pause['scheduled_pause'] and not second_pause['warning']

        # Timing tolerance covers fan transitions; it is bounded on both sides.
        for duration, eligible in [(474, False), (475, True), (485, True), (486, False)]:
            previous = dict(operating,
                            updated_at=(epoch + timedelta(minutes=duration - 1)).timestamp())
            candidate = power_tick(previous, duration, 0)
            assert candidate['scheduled_pause'] == eligible, (duration, candidate)

        # No delayed exemption after an early failure; no inherited exemption
        # after a reset, outage, invalid power, switch-off or sampling gap.
        for minute in range(131, 491):
            early = power_tick(early, minute, 0)
        assert early['warning'] and not early['scheduled_pause']
        for kwargs in [{'reset': True}, {'watts': 'unavailable'},
                       {'watts': 'unknown'}, {'watts': -1}, {'switch': 'off'},
                       {'switch': 'unavailable'}]:
            interrupted = power_tick(operating, 480, **({'watts': 0} | kwargs))
            assert interrupted['running_since'] is None
            assert not interrupted['scheduled_pause'] and not interrupted['warning']
            for minute in range(481, 492):
                interrupted = power_tick(interrupted, minute, 0)
            assert interrupted['warning'] and not interrupted['scheduled_pause']
        gap = power_tick(operating, 483, 0)
        assert gap['running_since'] is None and not gap['scheduled_pause']

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

        # Exercise the configured power observer, its attributes and the real
        # automation trigger. The observer already times failures, so the
        # trigger must not add another ten minutes after a pause overrun.
        power_block = package['template'][1]
        power_observer = power_block['sensor'][0]
        power_id = power_observer['default_entity_id']
        power_actions = Script(runtime, await async_validate_actions_config(
            runtime, cv.SCRIPT_SCHEMA(power_block['actions'])), 'TTR power test', 'template')
        power_warning = automations['garage_entfeuchter_ohne_leistung_warnung']
        triggers = {t['id']: t for t in power_warning['triggers']}
        assert triggers['ttk']['for'] == {'hours': 0, 'minutes': 10, 'seconds': 0}
        assert 'for' not in triggers['ttr']
        runtime.states.async_set(power_id, 'running', operating)
        runtime.states.async_set('sensor.ttr_57_entfeuchter_leistung', '0')
        for minute, expected in [(480, False), (511, False), (512, True)]:
            # Minute 511 uses the continuous pause from the macro test above.
            if minute == 511:
                current = power_tick(before_restart, 510, 0)
                runtime.states.async_set(power_id, 'paused', current)
            with patch('homeassistant.util.dt.now', return_value=epoch + timedelta(minutes=minute)):
                result = await power_actions.async_run({'trigger': SimpleNamespace(id='sample')}, Context())
            power = result.variables['power']
            attributes = {key: render(value, power=power)
                          for key, value in power_observer['attributes'].items()}
            runtime.states.async_set(power_id, str(minute), attributes)
            assert render(triggers['ttr']['value_template']) == expected, (minute, attributes)
        assert power_id in package['recorder']['exclude']['entities']

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
        for entity in (observer, power_observer, low_sensor,
                       next(e for b in package['template'] for e in b.get('binary_sensor', [])
                            if e['unique_id'] == 'garage_feuchte_ueber_60')):
            row = next(r for r in assignments if r['unique_id'] == entity['unique_id'])
            assert row['name'] == entity['name'] and row['area_id'] == 'garage'
        for aid in ('garage_ttr_entfeuchter_boost_an', 'garage_ttr_entfeuchter_boost_aus',
                    'garage_entfeuchter_ohne_leistung_warnung',
                    'garage_entfeuchter_startfeuchte_merker',
                    'garage_entfeuchter_boost_startfeuchte_merken', warn_id, boost_id, ok_id):
            row = next(r for r in assignments if r['domain'] == 'automation' and r['unique_id'] == aid)
            assert row['name'] == automations[aid]['alias'] and row['area_id'] == 'garage'
        # Four input booleans/numbers are internal helpers without area needs;
        # the unchanged whole-house digest deliberately has no garage assignment.
        print('Garage drying: time windows, peak progress, recovery/rebound, invalid input,')
        print('template state retention, independent notifications and CSV identity checks passed.')
        print('TTR power: ten-minute failures, eight-hour cycle, bounded safety pause,')
        print('restart/invalid input handling and configured trigger integration passed.')


asyncio.run(main())
