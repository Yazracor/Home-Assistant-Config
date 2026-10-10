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

from homeassistant.core import HomeAssistant
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
    permitted_text = "{% from 'solar_thermal.jinja' import cover_automation_permitted %}{% set f=cover_automation_permitted|as_function %}{{ f(cover, 'open') }}"
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
    guard = script['sequence'][0]['value_template']
    assert render(guard, cover_entity=cover, action_id='open', expected_mode='on')
    hass.states.async_set('binary_sensor.heizen_kuehlen_rueckmeldung', 'off')
    assert not render(guard, cover_entity=cover, action_id='open', expected_mode='on')
    assert script['mode'] == 'queued'

    # Check the actual trigger-template action and its rendered entity attributes.
    package = yaml.safe_load(open('/config/virtual/solar_thermal.yaml'))
    block = package['template'][1]
    rendered = render(block['actions'][0]['variables']['controller'], this=SimpleNamespace(attributes={}))
    assert isinstance(rendered['rooms'], dict)
    for value in block['sensor'][0]['attributes'].values():
        assert isinstance(render(value, controller=rendered), dict)
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

    print('Solar thermal behavior checks passed')
    await hass.async_stop()
    test_dir.cleanup()

asyncio.run(main())
