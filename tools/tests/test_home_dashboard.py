"""Offline checks for dashboard templates, using HA's real template environment.

docker run --rm -v "$PWD:/config:ro" ghcr.io/home-assistant/home-assistant:stable \
  python /config/tools/tests/test_home_dashboard.py

No running HA instance, integrations or service calls are used.
"""
import asyncio
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers import entity_registry as er, floor_registry as fr
from homeassistant.helpers.template import Template, async_load_custom_templates
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml


async def main():
    with tempfile.TemporaryDirectory(prefix="home-dashboard-") as directory:
        shutil.copytree("/config/custom_templates", directory + "/custom_templates")
        instance = HomeAssistant(directory)
        instance.config.time_zone = "Europe/Berlin"
        instance.data[dr.DATA_REGISTRY] = dr.DeviceRegistry(instance)
        for registry in (dr, er, ar, fr):
            await registry.async_load(instance, load_empty=True)
        await async_load_custom_templates(instance)

        def render(macro):
            return Template(
                "{% from 'dashboard_home.jinja' import " + macro + " %}"
                "{{ " + macro + "() }}", instance
            ).async_render()

        set_state = instance.states.async_set
        now = dt_util.utcnow()
        # Every Markdown card also renders before integrations have supplied data.
        dashboard = load_yaml("/config/dashboards/mein_zuhause.yaml")
        assert [v["path"] for v in dashboard["views"]] == [
            "zuhause", "garage", "sonne", "raeume"
        ]
        configuration = load_yaml("/config/configuration.yaml")
        assert configuration["lovelace"]["mode"] == "storage"
        assert list(configuration["lovelace"]["dashboards"]) == ["mein-zuhause"]

        def walk(value):
            if isinstance(value, dict):
                yield value
                for child in value.values():
                    yield from walk(child)
            elif isinstance(value, list):
                for child in value:
                    yield from walk(child)

        for card in walk(dashboard):
            assert not str(card.get("type", "")).startswith("custom:")
            if card.get("type") == "markdown":
                assert Template(card["content"], instance).async_render()
            # Warning flags are display-only, never acknowledgment switches.
            if card.get("entity", "").startswith("input_boolean.garage_entfeuchtung"):
                assert card["type"] == "simple-entity"
        assert "nicht verfügbar" in render("house_notes")
        assert "nicht verfügbar" in render("garage_air")
        assert "keine gültige" in render("garage_drying")
        assert "Heiz-/Kühlmodus fehlt" in render("shading_decisions")

        set_state("cover.aussenbereich_garage_garagentor", "closed")
        set_state("sensor.wifi_smart_switch_humidity", "59")
        set_state("sensor.garage_aussenluft_feuchte_bei_garagentemperatur", "48")
        for entity in ("input_boolean.garage_entfeuchtung_warnung_aktiv",
                       "input_boolean.garage_entfeuchtung_boost_warnung_aktiv"):
            set_state(entity, "off")
        set_state("switch.hitzeschutz_og_automatik", "on")
        set_state("sensor.hitzeschutz_manueller_jalousie_block", now.isoformat(),
                  {"blocked_since": {}})
        assert "Aktuell keine Hinweise" in render("house_notes")
        assert "weniger Feuchtigkeit" in render("garage_air")
        set_state("sensor.garage_aussenluft_feuchte_bei_garagentemperatur", "70")
        assert "mehr Feuchtigkeit" in render("garage_air")
        set_state("sensor.garage_aussenluft_feuchte_bei_garagentemperatur", "unavailable")
        assert "nicht verfügbar" in render("garage_air")
        set_state("cover.aussenbereich_garage_garagentor", "open")
        set_state("binary_sensor.aussenbereich_wetterstation_niederschlag", "on")
        set_state("input_boolean.garage_entfeuchtung_boost_warnung_aktiv", "on")
        notes = render("house_notes")
        assert "Garage offen bei Regen" in notes and "Boost-Warnung aktiv" in notes
        assert "/mein-zuhause/garage" in notes

        set_state("sensor.garage_entfeuchtung_verlauf", now.isoformat(),
                  {"valid": True, "humidity": 59, "reference_humidity": 61})
        assert "-2.0 Prozentpunkte" in render("garage_drying")
        set_state("sensor.garage_entfeuchtung_verlauf", now.isoformat(), {"valid": False})
        assert "keine gültige" in render("garage_drying")

        cover = "cover.eg_wohnzimmer_panorama"
        set_state(cover, "open", {"current_position": 50, "friendly_name": "Wohnzimmer Panorama"})
        set_state("group.hitzeschutz_automatik_jalousien", "on", {"entity_id": [cover]})
        set_state("binary_sensor.heizen_kuehlen_rueckmeldung", "on")
        set_state("sun.sun", "above_horizon")
        set_state("sensor.eg_wohnzimmer_thermostat_ist_temp", "20")
        set_state("sensor.eg_wohnzimmer_thermostat_soll_temp", "21")
        # A facade signal must not pretend missing thermal data allows opening.
        set_state("binary_sensor.hitzeschutz_fassade_wohnzimmer_panorama", "off")
        text = render("shading_decisions")
        assert "Thermikdaten fehlen oder sind veraltet" in text
        assert "aktuell freigegeben" not in text

        attributes = {
            "rooms": {"eg_wohnzimmer": {
                "valid": True, "trend_valid": True, "rise_per_hour": .4}},
            "decisions": {cover: {
                "action": "open", "reason": "Solarwaerme nutzen", "ready": True}}
        }
        set_state("sensor.hitzeschutz_thermik", now.isoformat(), attributes)
        assert "Öffnen · Solarwärme nutzen — aktuell freigegeben" in render("shading_decisions")
        assert "Wohnzimmer | 20.0 | 21.0 | +0.4" in render("room_temperatures")
        attributes["decisions"][cover]["ready"] = False
        set_state("sensor.hitzeschutz_thermik", now.isoformat(), attributes)
        assert "thermische Wartezeit läuft" in render("shading_decisions")
        set_state("sensor.hitzeschutz_manueller_jalousie_block", now.isoformat(),
                  {"blocked_since": {cover: now.isoformat()}})
        assert "manueller Override aktiv" in render("shading_decisions")
        assert "Manuell gesperrt: Wohnzimmer Panorama" in render("house_notes")

        with patch("homeassistant.util.dt.now", return_value=now + timedelta(minutes=5)):
            assert "Thermikdaten fehlen oder sind veraltet" in render("shading_decisions")
            assert "Wohnzimmer | 20.0 | 21.0 | —" in render("room_temperatures")
        set_state("binary_sensor.heizen_kuehlen_rueckmeldung", "off")
        assert "Öffnen · Fassade ohne Hitzeschutz" in render("shading_decisions")
        set_state("sun.sun", "below_horizon")
        assert "Keine solare Fahrtentscheidung bei Nacht" in render("shading_decisions")
        await instance.async_stop()
    print("Home dashboard checks passed: four views, native cards, missing/stale data, warnings and shading gates")


if __name__ == "__main__":
    asyncio.run(main())
