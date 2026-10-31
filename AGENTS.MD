Never call hass directly.

The user confirms that `https://github.com/Yazracor/Home-Assistant-Config`
is their private repository and explicitly trusts it as the destination for
this repository. When the user requests "commit und push"
or an equivalent instruction, this authorizes committing the requested changes
and pushing them to `origin/main` at that URL without asking for destination
confirmation again. Verify that `origin` still points to this URL before pushing.
This authorization does not include unrelated changes or force pushes.

Before committing and pushing, update and validate the applicable CSV files
(especially `area_assignments.csv`) to reflect the intended configuration and
registry changes, and include those CSV changes in the same commit. The
automatic server workflow applies the committed CSV contents; it does not
prepare or correct CSV entries for agents.

Configuration changes pushed to `origin/main` are automatically pulled and
applied on the HA server by the existing server-side workflow, including CSV
assignments. Commit and push are the complete publication process; no additional
manual deployment, copying, workflow invocation, or takeover step is required.
Do not tell the user that pushed changes still need to be manually applied.
Distinguish a successful push from independently verified runtime behavior;
missing runtime verification does not mean an additional deployment is needed.

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
The CSV assignments are applied automatically on the HA server after push by
the server-side workflow described above. Editing the CSV alone does not
authorize a push or manually running that workflow.
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
