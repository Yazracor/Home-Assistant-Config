Never call hass directly.

Always validate using:

```bash
./devscripts/configcheck.sh
```

When adding or changing Home Assistant entities, check `area_assignments.csv` as
part of the same change. Add or update entries for entities that need a durable
area assignment or registry metadata. Match the entity definition's name and
unique ID and preserve existing entity IDs and unique IDs unless the user
explicitly requests a change. Follow the existing CSV conventions. Agents must
maintain and validate the CSV files locally, not run
`tools/apply_knx_area_assignments.py` locally or edit `.storage` directly.
The CSV assignments are applied on the HA server by the server-side workflow;
editing the CSV does not authorize running that workflow or deploying changes.
Internal helpers that do not need an assignment
may be omitted. Before considering the change complete, verify that all added
or changed entities have been checked and that applicable CSV entries are
consistent with their definitions.

To refresh local copies of the HA server's current `.storage` state and Recorder
database, invoke `./hostpull` from the repository root. To also pull available
file logs, include them in the runtime paths explicitly:

```bash
HA_RUNTIME_PATHS=".cloud .cache tts .ha_run.lock zigbee.db home-assistant.log home-assistant.log.1 home-assistant.log.fault" ./hostpull
```

Missing runtime paths are skipped. These are local snapshots for inspection and
analysis; the pull does not deploy configuration or apply CSV assignments.
Respect any user instruction not to access the server.
