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

## Git-Hook nach `git pull`

Auf der Home-Assistant-Instanz kann die Area-Zuordnung automatisch nach einem
erfolgreichen `git pull` vorgemerkt werden:

```bash
cd /config
./devscripts/install-git-hooks.sh
```

Das installiert `.git/hooks/post-merge` als kleinen Wrapper, der das
versionierte Script `/config/devscripts/post-merge` aufruft. Änderungen am
versionierten Script greifen dadurch ohne erneute Hook-Installation. Der Hook
stoppt Home Assistant nicht direkt im Git-Prozess, sondern schreibt
`/config/.pending_knx_area_assignment` und startet den Registry-Patch detached
im Hintergrund. Dadurch kann der Pull, auch wenn er durch Home Assistant selbst
ausgelöst wurde, sauber zurückkehren, bevor Home Assistant Core gestoppt wird.

Das Script führt den Ablauf zweiphasig aus: Home Assistant Core stoppen,
bestehende Entities patchen, Home Assistant Core starten, auf die aktualisierte
Entity-Registry warten, nochmal stoppen, erneut patchen und wieder starten.
Damit werden sowohl bereits vorhandene als auch nach dem YAML-Update neu
geschriebene Entities passenden Räumen zugeordnet.

Der Hintergrundlauf schreibt nach `/config/.knx-area-assignment.log`. Die
Startverzögerung nach dem Pull kann mit `KNX_AREA_ASSIGNMENT_DELAY_SECONDS`
angepasst werden. Zum Stoppen und Starten von Home Assistant Core nutzt das
Script zuerst `ha`; wenn das Kommando in der Hook-Umgebung nicht verfügbar ist,
fällt es auf die Supervisor-API mit `SUPERVISOR_TOKEN` zurück. Für das
Registry-Patch-Script muss in der Hook-Umgebung Python verfügbar sein; falls
Python nicht im `PATH` liegt, kann der Pfad mit `PYTHON_BIN` gesetzt werden,
zum Beispiel in `/config/.knx-area-assignment.env`:

```bash
PYTHON_BIN=/usr/bin/python3
```

Wenn Python fehlt, schreibt der Runner Diagnoseinformationen inklusive eines
kompletten Filetrees ab `/` ins Log.

In Alpine-basierten Hook-Umgebungen installiert der Runner fehlendes Python
automatisch mit `apk add --no-cache python3`. Das kann mit
`KNX_AREA_ASSIGNMENT_AUTO_INSTALL_PYTHON=0` deaktiviert werden.

Der Installer setzt außerdem `git config pull.rebase false`. Commits auf der
Home-Assistant-Instanz sind deaktiviert; Änderungen sollen auf der Workstation
reviewt und committed werden.

## Lokaler Pull von `.storage` und Datenbank-Snapshot

Das lokale Script `./hostpull` zieht die `.storage`-Dateien vom
Home-Assistant-Host und erstellt zusätzlich einen konsistenten SQLite-Snapshot
der Datenbank auf dem Host:

```bash
./hostpull
```

Standardmäßig wird per SSH `sqlite3 /config/home-assistant_v2.db ".backup ..."`
auf dem Host ausgeführt. Die konsistente Backup-Datei wird anschließend lokal
als `./home-assistant_v2.db` ins Config-Verzeichnis geschrieben. Diese Datei ist
per `.gitignore` ausgeschlossen und kann von lokalen Prüf- und Analyse-Skripten
direkt verwendet werden.

Relevante Umgebungsvariablen:

```bash
HA_HOST=192.168.1.10
HA_USER=
HA_CONFIG_DIR=/config
HA_DB_PATH=/config/home-assistant_v2.db
HA_LOCAL_DB_PATH=./home-assistant_v2.db
HA_PULL_DB_SNAPSHOT=1
```

Mit `HA_PULL_DB_SNAPSHOT=0 ./hostpull` kann der Datenbank-Snapshot bei Bedarf
übersprungen werden.
