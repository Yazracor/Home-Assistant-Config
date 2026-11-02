"""Offline widget text and template-sensor update checks in the HA container.

docker run --rm -v "$PWD:/config:ro" ghcr.io/home-assistant/home-assistant:stable \
  python /config/tools/tests/test_iphone_widgets.py

Uses artificial states, empty registries and no external integrations.
"""
import asyncio
import csv
import shutil
import tempfile

from homeassistant import loader
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers import entity_registry as er, floor_registry as fr
from homeassistant.helpers.template import Template, async_load_custom_templates
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml


async def main():
    with tempfile.TemporaryDirectory(prefix="iphone-widget-test-") as directory:
        shutil.copytree("/config/custom_templates", directory + "/custom_templates")
        instance = HomeAssistant(directory)
        instance.config.time_zone = "Europe/Berlin"
        loader.async_setup(instance)
        instance.data[dr.DATA_REGISTRY] = dr.DeviceRegistry(instance)
        for registry in (dr, er, ar, fr):
            await registry.async_load(instance, load_empty=True)
        instance.config_entries = ConfigEntries(instance, {})
        await instance.config_entries.async_initialize()
        await async_load_custom_templates(instance)

        def render(macro):
            return Template(
                "{% from 'iphone_widgets.jinja' import " + macro + " %}"
                "{{ " + macro + "() }}", instance
            ).async_render()

        set_state = instance.states.async_set
        door = "cover.aussenbereich_garage_garagentor"
        rain = "binary_sensor.aussenbereich_wetterstation_niederschlag"
        warning = "input_boolean.garage_entfeuchtung_warnung_aktiv"
        boost = "input_boolean.garage_entfeuchtung_boost_warnung_aktiv"
        shading = "switch.hitzeschutz_og_automatik"
        humidity = "sensor.wifi_smart_switch_humidity"
        temperature = "sensor.wifi_smart_switch_temperature"
        outside = "sensor.aussenbereich_wetterstation_temperatur"
        assert render("headline") == "Status unvollständig"
        assert render("garage_line") == "Garage · Feuchte fehlt · Temperatur fehlt"
        assert render("weather_line") == "Außen · Temperatur fehlt · Regenstatus fehlt"
        for entity, value in {
            door: "closed", rain: "off", warning: "off", boost: "off", shading: "on",
            humidity: "59", temperature: "14.2", outside: "9.4"
        }.items():
            set_state(entity, value)
        assert render("headline") == "Keine wichtigen Hinweise"
        assert render("garage_line") == "Garage · 59 % · 14,2 °C"
        assert render("weather_line") == "Außen · 9,4 °C · kein Regen"

        # Highest priority wins, and missing data must not look like all-clear.
        for entity, value, expected in [
            (shading, "off", "⚠ Jalousie-Automatik aus"),
            (warning, "on", "⚠ Entfeuchtung prüfen"),
            (boost, "on", "⚠ Entfeuchtungs-Boost prüfen"),
            (door, "open", "⚠ Garage offen"),
            (rain, "on", "⚠ Garage offen bei Regen"),
            (door, "opening", "⚠ Garage offen bei Regen"),
            (rain, "unavailable", "⚠ Garage offen"),
        ]:
            set_state(entity, value)
            assert render("headline") == expected
        for entity, value in {door: "closed", warning: "off", boost: "off", shading: "on"}.items():
            set_state(entity, value)
        for entity in (door, warning, boost, shading):
            original = instance.states.get(entity).state
            set_state(entity, "unavailable")
            assert render("headline") == "Status unvollständig"
            set_state(entity, original)
        assert "Regenstatus fehlt" in render("weather_line")
        set_state(humidity, "unavailable")
        assert render("garage_line") == "Garage · Feuchte fehlt · 14,2 °C"
        set_state(humidity, "101")
        assert "Feuchte fehlt" in render("garage_line")
        set_state(humidity, "0")
        set_state(outside, "-2.5")
        assert render("garage_line") == "Garage · 0 % · 14,2 °C"
        assert "-2,5 °C" in render("weather_line")

        package = load_yaml("/config/virtual/iphone_widgets.yaml")
        definition = package["template"][0]["sensor"][0]
        with open("/config/area_assignments.csv") as stream:
            rows = list(csv.DictReader(stream))
        rows = [row for row in rows if row["expected_entity_id"] == definition["default_entity_id"]]
        assert len(rows) == 1
        assert rows[0]["unique_id"] == definition["unique_id"]
        assert rows[0]["name"] == definition["name"]
        assert rows[0]["area_id"] == "technik"

        # Exercise HA's actual dependency tracking through the imported macros.
        assert await async_setup_component(instance, "template", {"template": package["template"]})
        await instance.async_start()
        await instance.async_block_till_done()
        sensor = instance.states.get("sensor.iphone_hausstatus")
        assert sensor is not None
        assert sensor.state == sensor.attributes["upper_text"] == "Keine wichtigen Hinweise"
        assert sensor.attributes["lower_text"] == "Garage · 0 % · 14,2 °C"
        set_state(temperature, "15.1")
        await instance.async_block_till_done()
        sensor = instance.states.get("sensor.iphone_hausstatus")
        assert sensor.state == "Keine wichtigen Hinweise"
        assert sensor.attributes["lower_text"] == "Garage · 0 % · 15,1 °C"
        set_state(door, "open")
        await instance.async_block_till_done()
        sensor = instance.states.get("sensor.iphone_hausstatus")
        assert sensor.state == sensor.attributes["upper_text"] == "⚠ Garage offen"
        await instance.async_stop()
    print("iPhone widget checks passed: priority, missing data, formatting, CSV and live template updates")


if __name__ == "__main__":
    asyncio.run(main())
