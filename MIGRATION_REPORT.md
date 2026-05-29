# KNX-Migration FHEM → Home Assistant

## Ergebnis

- FHEM-KNX-Devices insgesamt: **61**
- erzeugte `light`-Entitäten: **33**
- erzeugte `cover`-Entitäten: **22**
- erzeugte `climate`-Entitäten: **1**
- erzeugte `binary_sensor`-Entitäten: **3**
- erzeugte `sensor`-Entitäten: **1**
- erzeugte `button`-Entitäten: **1**
- prüfpflichtige/nicht aktivierte Einträge: **4**

## Wichtige Annahmen

- Die Namen der erzeugten Entitäten entsprechen den FHEM-Device-Namen.
- Einfache DPT1-Beleuchtungsaktoren wurden als `light` und nicht als `switch` erzeugt.
- Dimmaktoren wurden als `light` mit `address`, `state_address`, `brightness_address`, `brightness_state_address` erzeugt.
- Jalousien wurden als `cover` mit `move_long_address`, `move_short_address`, `position_address`, `position_state_address` erzeugt, sofern die FHEM-/ETS-Zuordnung plausibel war.
- Für Jalousien wurde `travelling_time_up/down: 27` übernommen, weil die manuell angelegten KNX-Panel-Beispiele 27 s verwenden.
- `EG_Buero_Soll` wurde nicht zusätzlich als aktive `number` eingebunden, weil dieselbe Sollwert-Adresse bereits in `TH_EG_Buero` verwendet wird.
- Die `.storage/knx/config_store.json` wurde nicht generiert oder verändert.

## Abgleich mit bestehenden KNX-Panel-Entitäten

| Domain | Entity-ID | Gerätename | KNX-Konfiguration |
|---|---|---|---|
| light | `light.arbeitszimmer_decke` | `Decke` | `{"ga_switch": {"write": "3/0/60", "state": "3/0/63", "passive": []}, "ga_brightness": {"write": "3/0/62", "state": "3/0/64", "passive": []}, "color_temp_max": 6000.0, "sync_state": true, "color_temp_min": 2700.0}` |
| cover | `cover.garten` | `Garten` | `{"ga_up_down": {"write": "4/0/76", "passive": []}, "ga_position_state": {"state": "4/0/78", "passive": []}, "travelling_time_up": 27.0, "travelling_time_down": 27.0, "ga_step": {"write": "4/0/77", "passive": []}, "sync_state": true}` |
| cover | `cover.vorgarten` | `Vorgarten` | `{"ga_up_down": {"write": "4/0/80", "passive": []}, "ga_step": {"write": "4/0/81", "passive": []}, "ga_position_state": {"state": "4/0/82", "passive": []}, "travelling_time_up": 27.0, "travelling_time_down": 27.0, "sync_state": true}` |

## Doppelt verwendete Gruppenadressen

Diese Adressen werden in mehreren erzeugten Entitäten verwendet. Das kann korrekt sein, sollte aber geprüft werden.

- `4/0/14` – A4 OG Bad Panoramaf. R JP
  - `cover` `Jalousie_OG_Bad_Aussen_Balkon` Feld `position_state_address`
  - `cover` `Jalousie_OG_Bad_Aussen_Panorama` Feld `position_state_address`
- `4/0/15` – A4 OG Bad Panoramaf. JP
  - `cover` `Jalousie_OG_Bad_Aussen_Balkon` Feld `position_address`
  - `cover` `Jalousie_OG_Bad_Aussen_Panorama` Feld `position_address`

## Prüfliste / nicht aktivierte Einträge

| FHEM-Device | Adresse(n) | Grund |
|---|---|---|
| `EG_Buero_Soll` | `5/0/81` | Gleiche Sollwert-Adresse wie TH_EG_Buero; nicht zusätzlich als number aktiviert, um doppelte Bedienung desselben Gruppenobjekts zu vermeiden. |
| `TH_EG_Buero` | `5/0/75` | Erste DPT9.001-Adresse ohne FHEM-Alias; ETS-Name: --1A6 EG Gast Basis Sollwert. Nicht automatisch in climate eingebunden. |
| `Jal_OG_Schlafzimmer_Aussen_Front_All_lang` | `4/2/7` | Einzelne Jalousie-Gruppenadresse ohne Richtungspaar/Status; nicht als cover oder button aktiviert. |
| `KNX_Esszimmer.Tisch_knx` | `6/4/10` | ETS-Pfad/Funktion wirkt wie Funk-/Tasterfunktion, nicht wie Aktorausgang; nicht automatisch als light/switch aktiviert. |

## Installation

1. Vorher Home-Assistant-Backup erstellen.
2. Den Ordner `knx/`, die Datei `knx.yaml` und die ergänzte `configuration.yaml` in das Git-Repository übernehmen.
3. Wenn Du komplett auf YAML umstellst, die drei manuell im KNX-Panel angelegten Entitäten entfernen oder deaktivieren, sonst entstehen Duplikate.
4. In Home Assistant `Einstellungen → System → Reparaturen/Neustart → Konfiguration prüfen` ausführen.
5. Erst danach committen/pushen und per Git-Pull-Add-on deployen.


## Ergänzung: Räume und Stockwerke

In der Version `ha_knx_with_areas` wurden alle `sync_state`-Einträge aus den YAML-Dateien entfernt.

Zusätzlich wurden erzeugt:

- `.storage/core.floor_registry`
- `.storage/core.area_registry`
- `floors.csv`
- `areas.csv`
- `area_assignments.csv`
- `tools/apply_knx_area_assignments.py`
- `ROOMS_AND_FLOORS.md`

Home Assistant weist Entitäten/Geräte nicht direkt Stockwerken zu, sondern Areas; Areas werden anschließend Stockwerken zugeordnet. Bei YAML-basierten KNX-Entitäten entstehen in Home Assistant normalerweise Entitäten mit Unique-ID, aber keine eigenen KNX-Geräte. Daher setzt das Skript primär `area_id` in `core.entity_registry`; falls ein passendes `device_id` existiert, wird zusätzlich `core.device_registry` aktualisiert.
