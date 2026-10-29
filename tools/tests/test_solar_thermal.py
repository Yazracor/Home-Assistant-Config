"""Behavior checks in the HA container, using its actual Jinja environment.

Run: docker run --rm -v "$PWD:/config:ro" IMAGE \
     python /config/tools/tests/test_solar_thermal.py
No live integrations or service calls are started.
"""
import asyncio
import csv
import shutil
import tempfile
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.core import Context, HomeAssistant, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.script import Script, async_validate_actions_config
from homeassistant.helpers.template import Template, async_load_custom_templates
from homeassistant.helpers import device_registry as dr, entity_registry as er, area_registry as ar, floor_registry as fr
from homeassistant.util import dt as dt_util
import yaml


async def main():
    test_dir = tempfile.TemporaryDirectory(prefix='solar-thermal-test-')
    shutil.copytree('/config/custom_templates', test_dir.name + '/custom_templates')
    hass = HomeAssistant(test_dir.name)
    hass.config.latitude = 50.1026602
    hass.config.longitude = 8.2715918
    hass.config.time_zone = 'Europe/Berlin'
    hass.data[dr.DATA_REGISTRY] = dr.DeviceRegistry(hass)
    for registry in (dr, er, ar, fr):
        await registry.async_load(hass, load_empty=True)
    await async_load_custom_templates(hass)
    render = lambda text, **variables: Template(text, hass).async_render(variables)
    configs = render("{% from 'solar_thermal.jinja' import room_configs %}{% set f=room_configs|as_function %}{{ f() }}")
    timestamp = dt_util.utcnow()
    for room in configs:
        hass.states.async_set(f'sensor.{room}_thermostat_ist_temp', '20')
        hass.states.async_set(f'sensor.{room}_thermostat_soll_temp', '21')
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'on')
    hass.states.async_set('sensor.aussenbereich_wetterstation_temperatur', '5')
    hass.states.async_set('sensor.aussenbereich_wetterstation_helligkeit', '60000')
    hass.states.async_set('sun.sun', 'above_horizon', {'azimuth': 205, 'elevation': 25})
    snapshot_text = "{% from 'solar_thermal.jinja' import controller_snapshot %}{% set f=controller_snapshot|as_function %}{{ f(previous) }}"

    def snapshot(previous=None, minutes=0):
        with patch('homeassistant.util.dt.now', return_value=timestamp + timedelta(minutes=minutes)):
            return render(snapshot_text, previous=previous or {})

    state = snapshot()
    cover = 'cover.eg_wohnzimmer_balkon'
    assert state['decisions'][cover]['action'] == 'open', state
    assert not state['decisions'][cover]['ready']
    state = snapshot(state, 10)
    assert state['decisions'][cover]['ready']
    assert len(state['decisions']) == 18
    for shared_cover in ('cover.og_flur_fenster', 'cover.og_treppe'):
        assert state['decisions'][shared_cover]['rooms'] == ['og_schlafzimmer']
    assert 'cover.aussenbereich_balkon_sonnensegel' not in state['decisions']
    hass.states.async_set('sensor.eg_wohnzimmer_thermostat_ist_temp', '21.4')
    state = snapshot(state, 11)
    assert state['rooms']['eg_wohnzimmer']['overheated']
    assert state['decisions'][cover]['action'] == 'close'
    assert not state['decisions'][cover]['ready']
    state = snapshot(state, 13)
    assert state['decisions'][cover]['ready']
    hass.states.async_set('sensor.eg_wohnzimmer_thermostat_ist_temp', '21.0')
    state = snapshot(state, 14)
    assert state['rooms']['eg_wohnzimmer']['overheated']  # hysteresis
    hass.states.async_set('sensor.eg_wohnzimmer_thermostat_ist_temp', '20.6')
    state = snapshot(state, 15)
    assert not state['rooms']['eg_wohnzimmer']['overheated']
    assert state['decisions'][cover]['action'] == 'open'

    # Regression across at least 20 minutes predicts overheating before actual excess.
    hass.states.async_set('sensor.eg_wohnzimmer_thermostat_ist_temp', '20.9')
    previous = {'samples': {'eg_wohnzimmer': [
        [(timestamp + timedelta(minutes=m)).timestamp(), 20.5 + m*.02, 21.0]
        for m in range(21)
    ]}}
    state = snapshot(previous, 21)
    room = state['rooms']['eg_wohnzimmer']
    assert room['trend_valid'] and room['rise_per_hour'] > 1
    assert room['overheated'] and room['temperature'] < room['target'], room
    # A changed target invalidates the old regression history.
    hass.states.async_set('sensor.eg_wohnzimmer_thermostat_soll_temp', '22')
    state = snapshot(previous, 21)
    assert not state['rooms']['eg_wohnzimmer']['trend_valid']
    assert not state['rooms']['eg_wohnzimmer']['overheated']
    # Both workroom sensors are respected; warmer zone can veto solar opening.
    hass.states.async_set('sensor.eg_arbeitszimmer_flur_thermostat_ist_temp', '22')
    state = snapshot()
    assert state['decisions']['cover.eg_arbeitszimmer_garten']['action'] == 'close'
    assert len(state['decisions']['cover.eg_arbeitszimmer_garten']['rooms']) == 2
    # Existing high-lux protection remains effective even with a low clear-sky index.
    hass.states.async_set('sensor.aussenbereich_wetterstation_helligkeit', '20000')
    state = snapshot()
    assert state['decisions']['cover.eg_arbeitszimmer_garten']['action'] == 'close'
    hass.states.async_set('sensor.aussenbereich_wetterstation_helligkeit', '60000')
    # Mild weather reduces temperature allowance.
    hass.states.async_set('sensor.aussenbereich_wetterstation_temperatur', '21')
    state = snapshot()
    assert state['rooms']['eg_kueche']['shade_margin'] == .1
    # Missing room values never become zero degrees and never trigger solar opening.
    hass.states.async_set('sensor.eg_kueche_thermostat_ist_temp', 'unavailable')
    state = snapshot()
    assert not state['rooms']['eg_kueche']['valid']
    assert state['decisions']['cover.eg_kueche_balkon']['action'] == 'none'
    # Cooling and unknown mode do not produce heating commands.
    for mode in ('off', 'unknown'):
        hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', mode)
        state = snapshot()
        assert all(d['action'] == 'none' for d in state['decisions'].values())
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'on')
    # Weak sun opens only after 30 minutes, and darkness never causes solar opening.
    hass.states.async_set('sensor.aussenbereich_wetterstation_helligkeit', '1000')
    state = snapshot()
    assert state['decisions'][cover]['reason'] == 'Sonne zu schwach'
    assert not snapshot(state, 29)['decisions'][cover]['ready']
    assert snapshot(state, 30)['decisions'][cover]['ready']
    hass.states.async_set('sun.sun', 'below_horizon', {'azimuth': 300, 'elevation': -1})
    state = snapshot()
    assert all(d['action'] == 'none' for d in state['decisions'].values())
    # Clear-sky reference and low-sun fallback are finite.
    index_text = "{% from 'solar_thermal.jinja' import clear_sky_index %}{% set f=clear_sky_index|as_function %}{{ f() }}"
    assert render(index_text) is None
    hass.states.async_set('sun.sun', 'above_horizon', {'azimuth': 205, 'elevation': 25})
    hass.states.async_set('sensor.aussenbereich_wetterstation_helligkeit', '200000')
    assert render(index_text) == 2
    hass.states.async_set('sensor.aussenbereich_wetterstation_helligkeit', 'unavailable')
    state = snapshot()
    assert all(d['action'] == 'none' for d in state['decisions'].values())

    # Final guard prevents old facade commands fighting the thermal decision.
    allowed_text = "{% from 'solar_thermal.jinja' import cover_action_allowed %}{% set f=cover_action_allowed|as_function %}{{ f(cover, action) }}"
    hass.states.async_set('sensor.hitzeschutz_thermik', timestamp.isoformat(), {'decisions': {cover: {'action':'open', 'ready':True}}})
    assert render(allowed_text, cover=cover, action='open')
    assert not render(allowed_text, cover=cover, action='close')
    hass.states.async_set('sensor.hitzeschutz_thermik', 'unavailable')
    assert not render(allowed_text, cover=cover, action='open')
    assert render(allowed_text, cover=cover, action='close')
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'off')
    assert render(allowed_text, cover=cover, action='close')
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'unknown')
    assert not render(allowed_text, cover=cover, action='open')
    assert render(allowed_text, cover=cover, action='close')

    # Shared bedroom temperatures control each cover at its own facade direction.
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'on')
    hass.states.async_set('sensor.aussenbereich_wetterstation_helligkeit', '60000')
    hass.states.async_set('sensor.og_schlafzimmer_thermostat_soll_temp', '21')
    for shared_cover, azimuth in (('cover.og_flur_fenster', 295), ('cover.og_treppe', 115)):
        hass.states.async_set('sun.sun', 'above_horizon', {'azimuth': azimuth, 'elevation': 25})
        hass.states.async_set('sensor.og_schlafzimmer_thermostat_ist_temp', '21.5')
        hot = snapshot()
        assert hot['decisions'][shared_cover]['action'] == 'close'
        assert snapshot(hot, 2)['decisions'][shared_cover]['ready']
        hass.states.async_set('sensor.og_schlafzimmer_thermostat_ist_temp', '20.5')
        cold = snapshot(hot, 3)
        assert cold['decisions'][shared_cover]['action'] == 'open'
        assert snapshot(cold, 13)['decisions'][shared_cover]['ready']
    hass.states.async_set('sun.sun', 'above_horizon', {'azimuth': 205, 'elevation': 25})

    # Last-moment guard: switch, marker, TV, cooldown, position and queued mode.
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'on')
    hass.states.async_set('sensor.hitzeschutz_thermik', timestamp.isoformat(), {'decisions': {cover: {'action':'open', 'ready':True}}})
    hass.states.async_set(cover, 'closed', {'current_position': 0})
    hass.states.async_set('group.hitzeschutz_automatik_jalousien', 'closed', {'entity_id': [cover]})
    hass.states.async_set('switch.hitzeschutz_og_automatik', 'on')
    hass.states.async_set('media_player.wohnzimmer_samsung_fernseher', 'off')
    hass.states.async_set('sensor.hitzeschutz_manueller_jalousie_block', timestamp.isoformat(), {'blocked_since': {}})
    permitted_text = "{% from 'cover_control.jinja' import cover_automation_permitted %}{% set f=cover_automation_permitted|as_function %}{{ f(cover, 'open') }}"
    assert render(permitted_text, cover=cover)
    hass.states.async_set('switch.hitzeschutz_og_automatik', 'off')
    assert not render(permitted_text, cover=cover)
    hass.states.async_set('switch.hitzeschutz_og_automatik', 'on')
    hass.states.async_set('sensor.hitzeschutz_manueller_jalousie_block', timestamp.isoformat(), {'blocked_since': {cover: timestamp.isoformat()}})
    assert not render(permitted_text, cover=cover)
    hass.states.async_set('sensor.hitzeschutz_manueller_jalousie_block', timestamp.isoformat(), {'blocked_since': {}})
    hass.states.async_set('media_player.wohnzimmer_samsung_fernseher', 'on')
    assert not render(permitted_text, cover=cover)
    hass.states.async_set('media_player.wohnzimmer_samsung_fernseher', 'off')
    hass.states.async_set(cover, 'opening', {'current_position': 10})
    assert not render(permitted_text, cover=cover)
    hass.states.async_set(cover, 'open', {'current_position': 100})
    assert not render(permitted_text, cover=cover)
    hass.states.async_set(cover, 'closed', {'current_position': 0})
    # The guard in the actual command script rejects a queued command after mode change.
    script = yaml.safe_load(open('/config/scripts.yaml'))['hitzeschutz_jalousie_automatisieren']
    guard = script['sequence'][0]['variables']['result']
    assert render(guard, cover_entity=cover, action_id='open', expected_mode='on')['allowed']
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'off')
    assert not render(guard, cover_entity=cover, action_id='open', expected_mode='on')['allowed']
    assert script['mode'] == 'queued'

    # Check the actual trigger-template action and its rendered entity attributes.
    package = yaml.safe_load(open('/config/virtual/solar_thermal.yaml'))
    block = package['template'][1]
    hass.states.async_remove('sensor.hitzeschutz_thermik')
    rendered = render(block['actions'][0]['variables']['controller'])
    assert isinstance(rendered['rooms'], dict)
    for value in block['sensor'][0]['attributes'].values():
        assert isinstance(render(value, controller=rendered), dict)
    # Run the configured actions without an injected `this`, as the trigger
    # coordinator does. Persist the resulting sensor attributes between ticks.
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'on')
    hass.states.async_set('sun.sun', 'above_horizon', {'azimuth': 224.3, 'elevation': 21.6})
    hass.states.async_set('sensor.og_bad_thermostat_ist_temp', '23.82')
    hass.states.async_set('sensor.og_bad_thermostat_soll_temp', '22')
    action_config = await async_validate_actions_config(hass, cv.SCRIPT_SCHEMA(block['actions']))
    actions = Script(hass, action_config, 'Thermal state retention check', 'template')
    bad_cover = 'cover.og_bad_panorama_aussen'
    since = None
    for minute in range(23):
        if minute == 22:
            hass.states.async_set('sensor.og_bad_thermostat_ist_temp', '22')
        with patch('homeassistant.util.dt.now', return_value=timestamp + timedelta(minutes=minute)):
            result = await actions.async_run({}, Context())
        assert result is not None
        controller = result.variables['controller']
        decision = controller['decisions'][bad_cover]
        if since is None:
            since = decision['since']
        assert decision['action'] == 'close'
        assert decision['since'] == since, (minute, decision)
        assert decision['ready'] == (minute >= 2), (minute, decision)
        assert len(controller['samples']['og_bad']) == minute + 1
        assert controller['rooms']['og_bad']['trend_valid'] == (minute >= 20)
        assert controller['rooms']['og_bad']['overheated']
        attributes = {
            key: render(value, controller=controller)
            for key, value in block['sensor'][0]['attributes'].items()
        }
        hass.states.async_set('sensor.hitzeschutz_thermik', str(minute), attributes)
    # Validate durable metadata and all cover-to-thermostat room mappings.
    with open('/config/area_assignments.csv', newline='') as stream:
        assignments = list(csv.DictReader(stream))
    by_entity = {row['expected_entity_id']: row for row in assignments}
    for room_id, covers in configs.items():
        temp = by_entity['sensor.' + room_id + '_thermostat_ist_temp']
        target = by_entity['sensor.' + room_id + '_thermostat_soll_temp']
        assert temp['area_id'] == target['area_id']
        for entity in covers:
            if entity in ('cover.og_flur_fenster', 'cover.og_treppe'):
                assert room_id == 'og_schlafzimmer'
                assert by_entity[entity]['area_id'] == ('flur_og' if entity == 'cover.og_flur_fenster' else 'treppe_og')
                assert 'Schlafzimmer-Ist-/Solltemperatur' in by_entity[entity]['notes']
            else:
                assert by_entity[entity]['area_id'] == temp['area_id'], (room_id, entity)
    for block in package['template']:
        for entity in block.get('sensor', []):
            row = by_entity[entity['default_entity_id']]
            assert row['unique_id'] == entity['unique_id'] and row['name'] == entity['name']
    for entity in package['automation']:
        row = next(r for r in assignments if r['domain'] == 'automation' and r['unique_id'] == entity['id'])
        assert row['name'] == entity['alias']
    for domain, unique_id in [('sensor','hitzeschutz_clear_sky_index'), ('sensor','hitzeschutz_thermik'), ('automation','hitzeschutz_solarwaerme_regeln'), ('automation','hitzeschutz_kuehlmodus_uebernehmen')]:
        assert sum(row['domain'] == domain and row['unique_id'] == unique_id for row in assignments) == 1
    # The real floor registry enforces OG opening at 10:00, also in the final guard.
    floor = fr.async_get(hass).async_create('Obergeschoss')
    area = ar.async_get(hass).async_create('Buro OG', floor_id=floor.floor_id)
    upstairs = 'cover.og_buro_fenster'
    entity = er.async_get(hass).async_get_or_create('cover', 'test', 'test_upstairs', suggested_object_id='og_buro_fenster')
    er.async_get(hass).async_update_entity(entity.entity_id, area_id=area.id)
    hass.states.async_set(upstairs, 'closed', {'current_position': 0})
    hass.states.async_set('group.hitzeschutz_automatik_jalousien', 'closed', {'entity_id': [cover, upstairs]})
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'off')
    with patch('homeassistant.util.dt.now', return_value=timestamp.replace(hour=9)):
        assert not render(permitted_text, cover=upstairs)
    with patch('homeassistant.util.dt.now', return_value=timestamp.replace(hour=10)):
        assert render(permitted_text, cover=upstairs)

    # Reproduce the real failure: physical central-button commands arrive while
    # an unrelated automatic drive is active. Test the configured sensor filter
    # and attribute template, not an injected manual block alone.
    manual_template = yaml.safe_load(open('/config/templates.yaml'))[0]
    sensor = manual_template['sensor'][0]
    manual_condition = manual_template['condition'][0]['value_template']
    block_template = sensor['attributes']['blocked_since']
    all_covers = {entity for entities in configs.values() for entity in entities}
    all_covers.update(['cover.og_bad_balkon_links', 'cover.og_bad_balkon_mitte', 'cover.og_bad_balkon_rechts'])
    for entity_id in all_covers:
        hass.states.async_set(entity_id, 'closed', {'current_position': 0})
    hass.states.async_set('input_boolean.hitzeschutz_automatik_fahrbefehl_aktiv', 'on')
    auto_context = Context(user_id='automatic-script-started-by-user')
    hass.states.async_set('script.hitzeschutz_jalousie_automatisieren', 'on', context=auto_context)

    def manual_trigger(kind, data, context=None):
        return SimpleNamespace(id=kind, event=SimpleNamespace(data=data, context=context or Context()))

    touched_text = "{% from 'manual_control.jinja' import manual_cover_entities %}{% set f=manual_cover_entities|as_function %}{{ f(trigger.id, trigger.event.data, trigger.event.context.user_id, trigger.event.context.id) }}"
    manual_text = "{% from 'manual_control.jinja' import cover_manual_blocked %}{% set f=cover_manual_blocked|as_function %}{{ f(cover) }}"
    central = manual_trigger('knx', {'destination': '1/2/6', 'source': '1.1.43', 'direction': 'Incoming', 'data': 1})
    assert render(manual_condition, trigger=central)
    affected = render(touched_text, trigger=central)
    assert 'cover.og_bad_panorama_aussen' in affected
    assert 'cover.og_buro_fenster' in affected
    assert 'cover.eg_kueche_balkon' not in affected
    entries = render(block_template, trigger=central, this=SimpleNamespace(attributes={'blocked_since': {}}))
    if isinstance(entries, str):
        import json
        entries = json.loads(entries)
    hass.states.async_set('sensor.hitzeschutz_manueller_jalousie_block', timestamp.isoformat(), {'blocked_since': entries})
    assert render(manual_text, cover='cover.og_bad_panorama_aussen')
    assert not render(manual_text, cover='cover.eg_kueche_balkon')
    for direction, source in [('Outgoing', '15.15.250'), ('Incoming', '15.15.250'), ('Incoming', '1.1.15')]:
        own_knx = manual_trigger('knx', {'destination': '1/2/6', 'source': source, 'direction': direction})
        assert not render(manual_condition, trigger=own_knx)
    homekit = manual_trigger('homekit', {'entity_id': cover})
    assert render(manual_condition, trigger=homekit)
    service = {'domain': 'cover', 'service': 'close_cover', 'service_data': {'entity_id': [cover]}}
    assert render(manual_condition, trigger=manual_trigger('service', service, Context(user_id='manual-user')))
    assert not render(manual_condition, trigger=manual_trigger('service', service))
    assert not render(manual_condition, trigger=manual_trigger('service', service, auto_context))
    # Each managed blind has the same four-hour manual lock, independent of floor.
    entries = {entity: timestamp.isoformat() for entity in all_covers}
    hass.states.async_set('sensor.hitzeschutz_manueller_jalousie_block', timestamp.isoformat(), {'blocked_since': entries})
    for entity in all_covers:
        assert render(manual_text, cover=entity)
        with patch('homeassistant.util.dt.now', return_value=timestamp + timedelta(hours=4)):
            assert not render(manual_text, cover=entity)
    # A child lock vetoes the virtual parent; a parent lock vetoes its children.
    for locked, checked in [('cover.og_bad_balkon_links', 'cover.og_bad_balkon'), ('cover.og_bad_balkon', 'cover.og_bad_balkon_rechts')]:
        hass.states.async_set('sensor.hitzeschutz_manueller_jalousie_block', timestamp.isoformat(), {'blocked_since': {locked: timestamp.isoformat()}})
        assert render(manual_text, cover=checked)
        assert not render(manual_text, cover='cover.og_bad_panorama_aussen')
    hass.states.async_set('sensor.hitzeschutz_manueller_jalousie_block', 'unavailable')
    assert render(manual_text, cover=cover)

    # Run the real queued command script against fake services only. A manual
    # lock acquired after enqueueing must veto the second drive when it starts.
    hass.states.async_set('sensor.hitzeschutz_manueller_jalousie_block', timestamp.isoformat(), {'blocked_since': {}})
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'off')
    second_cover = 'cover.kg_zimmer_sinja_jalousie'
    hass.states.async_set('group.hitzeschutz_automatik_jalousien', 'closed', {'entity_id': [cover, second_cover]})
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def fake_cover_service(call):
        calls.append(call.data['entity_id'])
        started.set()
        await release.wait()

    hass.services.async_register('cover', 'open_cover', fake_cover_service)
    hass.services.async_register('cover', 'close_cover', fake_cover_service)
    actions = await async_validate_actions_config(hass, cv.SCRIPT_SCHEMA(script['sequence']))
    command = Script(hass, actions, 'Central cover regression check', 'script', script_mode=script['mode'], max_runs=script['max'])
    first = asyncio.create_task(command.async_run({'cover_entity': cover, 'action_id': 'open', 'expected_mode': 'off'}, Context()))
    await asyncio.wait_for(started.wait(), timeout=5)
    queued = asyncio.create_task(command.async_run({'cover_entity': second_cover, 'action_id': 'open', 'expected_mode': 'off'}, Context()))
    # Yield until the second run is queued behind the blocked fake service.
    for _ in range(10):
        if command.runs == 2:
            break
        await asyncio.sleep(0)
    assert command.runs == 2
    hass.states.async_set('sensor.hitzeschutz_manueller_jalousie_block', timestamp.isoformat(), {'blocked_since': {second_cover: timestamp.isoformat()}})
    release.set()
    first_result, queued_result = await asyncio.wait_for(asyncio.gather(first, queued), timeout=5)
    assert first_result.service_response['performed']
    assert not queued_result.service_response['performed']
    assert 'manueller Override aktiv' in queued_result.service_response['reasons']
    assert len(calls) == 1
    hass.states.async_set(cover, 'opening', {'current_position': 1})
    repeated = await command.async_run({'cover_entity': cover, 'action_id': 'open'}, Context())
    assert not repeated.service_response['performed'] and len(calls) == 1
    # The batch path retains the central per-blind authorization, but sends
    # no status notifications for successful drives or expected manual locks.
    notifications = []

    async def dispatch_cover(call):
        result = await command.async_run(dict(call.data), call.context)
        return result.service_response

    async def capture_notification(call):
        notifications.append(call.data['notification_payload'])

    hass.services.async_register('script', 'hitzeschutz_jalousie_automatisieren', dispatch_cover, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register('script', 'hitzeschutz_jalousien_sammel_benachrichtigen', capture_notification)
    hass.states.async_set(cover, 'closed', {'current_position': 0})
    scripts = yaml.safe_load(open('/config/scripts.yaml'))
    batch_actions = await async_validate_actions_config(hass, cv.SCRIPT_SCHEMA(scripts['hitzeschutz_jalousien_checks_pruefen']['sequence']))
    batch = Script(hass, batch_actions, 'Batch cover regression check', 'script')
    await batch.async_run({'checks': [{'facade_name': 'Regression', 'action_id': 'open', 'cover_entities': [second_cover, cover]}]}, Context())
    assert len(calls) == 2
    assert notifications == [], notifications
    # Existing callers of the compatibility script must also remain silent.
    hass.services.async_register('notify', 'mobile_app_torbens_iphone', capture_notification)
    silent_actions = await async_validate_actions_config(hass, cv.SCRIPT_SCHEMA(scripts['hitzeschutz_jalousien_sammel_benachrichtigen']['sequence']))
    silent = Script(hass, silent_actions, 'Silent cover notification compatibility check', 'script')
    await silent.async_run({'notification_payload': {'summaries': ['Regression'], 'details': ['Oeffnen ausgeloest']}}, Context())
    assert notifications == [], notifications

    # Physical tests found raised shutters despite HA/KNX reporting 0 percent.
    # The hourly close recheck must traverse the real facade/batch/command path,
    # while ordinary minute ticks and every other guard retain their behavior.
    baseline = len(calls)
    hass.states.async_set('sensor.hitzeschutz_manueller_jalousie_block', timestamp.isoformat(), {'blocked_since': {}})
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'on')
    hass.states.async_set('sensor.hitzeschutz_thermik', timestamp.isoformat(), {'decisions': {cover: {'action': 'close', 'ready': True}}})
    hass.states.async_set(cover, 'closed', {'current_position': 0})
    request = {'cover_entity': cover, 'action_id': 'close', 'expected_mode': 'on'}
    ordinary = await command.async_run(request, Context())
    assert not ordinary.service_response['performed'] and len(calls) == baseline
    retry_request = dict(request, recheck_closed=True)
    retried = await command.async_run(retry_request, Context())
    assert retried.service_response['performed'] and len(calls) == baseline + 1

    async def rejected_retry(reason):
        before = len(calls)
        result = await command.async_run(retry_request, Context())
        assert not result.service_response['performed'], result.service_response
        assert reason in result.service_response['reasons'], result.service_response
        assert len(calls) == before

    for moving in ['opening', 'closing']:
        hass.states.async_set(cover, moving, {'current_position': 0})
        await rejected_retry('Jalousie faehrt bereits')
    hass.states.async_set(cover, 'unavailable')
    await rejected_retry('Jalousie nicht verfuegbar')
    hass.states.async_set(cover, 'closed', {'current_position': 0})
    hass.states.async_set('sensor.hitzeschutz_manueller_jalousie_block', timestamp.isoformat(), {'blocked_since': {cover: timestamp.isoformat()}})
    await rejected_retry('manueller Override aktiv')
    hass.states.async_set('sensor.hitzeschutz_manueller_jalousie_block', timestamp.isoformat(), {'blocked_since': {}})
    hass.states.async_set('switch.hitzeschutz_og_automatik', 'off')
    await rejected_retry('Automatik aus')
    hass.states.async_set('switch.hitzeschutz_og_automatik', 'on')
    hass.states.async_set('group.hitzeschutz_automatik_jalousien', 'closed', {'entity_id': []})
    await rejected_retry('nicht im Automatik-Tag')
    hass.states.async_set('group.hitzeschutz_automatik_jalousien', 'closed', {'entity_id': [cover]})
    hass.states.async_set('media_player.wohnzimmer_samsung_fernseher', 'on')
    await rejected_retry('Fernseher im Wohnzimmer an')
    hass.states.async_set('media_player.wohnzimmer_samsung_fernseher', 'off')
    hass.states.async_set('sensor.hitzeschutz_thermik', timestamp.isoformat(), {'decisions': {cover: {'action': 'open', 'ready': True}}})
    await rejected_retry('thermische Freigabe fehlt')
    hass.states.async_set('sensor.hitzeschutz_thermik', timestamp.isoformat(), {'decisions': {cover: {'action': 'close', 'ready': False}}})
    await rejected_retry('thermische Freigabe fehlt')
    hass.states.async_set('sensor.hitzeschutz_thermik', timestamp.isoformat(), {'decisions': {cover: {'action': 'close', 'ready': True}}})
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'off')
    await rejected_retry('Heiz-/Kuehlmodus geaendert')
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'on')
    hass.states.async_set(cover, 'open', {'current_position': 100})
    opening = await command.async_run(dict(retry_request, action_id='open'), Context())
    assert not opening.service_response['performed']
    assert 'Zielposition bereits erreicht' in opening.service_response['reasons']
    hass.states.async_set(cover, 'closed', {'current_position': 0})

    async def dispatch_batch(call):
        await batch.async_run(dict(call.data), call.context)

    hass.services.async_register('script', 'hitzeschutz_jalousien_checks_pruefen', dispatch_batch)
    facades = render("{% from 'heat_protection.jinja' import facade_configs %}{% set f=facade_configs|as_function %}{{ f() }}")
    for facade in facades.values():
        hass.states.async_set(facade['sensor'], 'off')
    hass.states.async_set('binary_sensor.hitzeschutz_fassade_sud', 'on')
    facade_actions = await async_validate_actions_config(hass, cv.SCRIPT_SCHEMA(scripts['hitzeschutz_jalousien_fassadenstatus_pruefen']['sequence']))
    facade_script = Script(hass, facade_actions, 'Hourly close facade regression check', 'script')
    automations = yaml.safe_load(open('/config/automations.yaml'))
    hourly = next(a for a in automations if a['id'] == 'solar_heat_protection_blind_notification_periodic')
    assert hourly['triggers'] == [{'trigger': 'time_pattern', 'minutes': '0'}]
    hourly_data = hourly['actions'][0]['data']
    assert hourly_data['recheck_closed'] is True and hourly_data['min_facade_state_seconds'] == 600
    # Skip facade debounce in this isolated call; its timestamp was just seeded.
    before = len(calls)
    await facade_script.async_run(dict(hourly_data, min_facade_state_seconds=0), Context())
    assert len(calls) == before + 1
    assert calls[-1] == [cover]
    hourly_open = next(a for a in automations if a['id'] == 'solar_heat_protection_blind_open_notification_hourly')
    assert 'recheck_closed' not in hourly_open['actions'][0]['data']
    # Metadata of all changed entities remains consistent with the definitions.
    row = by_entity['script.hitzeschutz_jalousie_automatisieren']
    assert row['name'] == script['alias'] and row['unique_id'] == 'hitzeschutz_jalousie_automatisieren'
    assert by_entity['sensor.hitzeschutz_manueller_jalousie_block']['unique_id'] == sensor['unique_id']

    print('Solar thermal behavior checks passed')
    await hass.async_stop()
    test_dir.cleanup()

asyncio.run(main())
