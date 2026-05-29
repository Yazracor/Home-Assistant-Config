# Home-Assistant-KNX-Konfiguration aus FHEM/ETS

Enthaltene Dateien:

- `configuration.yaml` – Deine bestehende Datei, ergänzt um `knx: !include knx.yaml`
- `knx.yaml` – zentrale KNX-Include-Datei
- `knx/lights.yaml`
- `knx/covers.yaml`
- `knx/climate.yaml`
- `knx/binary_sensors.yaml`
- `knx/sensors.yaml`
- `knx/buttons.yaml`
- `knx/review_unmapped.yaml.disabled` – prüfpflichtige, nicht eingebundene Einträge
- `knx/numbers_review.yaml.disabled` – optionale Number-Entität für `EG_Buero_Soll`
- `MIGRATION_REPORT.md`
- `migration_mapping.csv`

Wichtig: Wenn die KNX-Panel-Entitäten aus `.storage/knx/config_store.json` aktiv bleiben, können Duplikate entstehen. Vor der YAML-Umstellung entweder die Panel-Entitäten löschen/deaktivieren oder die entsprechenden YAML-Einträge vorübergehend entfernen.


## Räume und Stockwerke

Dieses Paket enthält zusätzlich `ROOMS_AND_FLOORS.md`, `floors.csv`, `areas.csv`, `area_assignments.csv`, `.storage/core.floor_registry`, `.storage/core.area_registry` und `tools/apply_knx_area_assignments.py`.

Die KNX-YAML-Dateien enthalten keine `sync_state`-Einträge mehr.

Für die automatische Raumzuordnung nach dem ersten erfolgreichen HA-Start mit der KNX-YAML:

```bash
ha core stop
python3 /config/tools/apply_knx_area_assignments.py --config-dir /config
ha core start
```
