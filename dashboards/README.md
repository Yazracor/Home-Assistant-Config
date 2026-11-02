# Mein Zuhause

Zusätzliches YAML-Dashboard unter `/mein-zuhause/zuhause`, in der Seitenleiste
als **Mein Zuhause** registriert. Die Standardübersicht bleibt im Storage-Modus;
vorhandene UI-Dashboards und die Auswahl des persönlichen Standard-Dashboards
werden nicht verändert.

Die vier Ansichten verwenden ausschließlich eingebaute Karten:

- **Zuhause:** relevante Hinweise mit Links zu den Details, Anwesenheit, Wetter
  und häufig benötigte Schalter.
- **Garage & Werkstatt:** Tor, Präsenz, Licht, Heizung, Entfeuchter und getrennte
  24-Stunden-Verläufe für Feuchte, Temperatur, Leistung und Betriebszustände.
- **Sonne & Raumklima:** Ist-/Solltemperaturen, verfügbare Trends, Fassadenstatus
  und aktuelle Freigaben samt Sperrgründen aus den bestehenden Steuer-Makros.
- **Räume:** vorhandene Bedienelemente für 32 Räume, nach Stockwerken geordnet.
  Thermostate und Medien öffnen über ihre Zeile den jeweiligen Detaildialog.

Die Dateien der Ansichten sind relativ zu `mein_zuhause.yaml` eingebunden.
`custom_templates/dashboard_home.jinja` enthält ausschließlich Darstellung;
Steuerung, Automationen, Entitäts-IDs und Unique-IDs bleiben unverändert.
Das Dashboard selbst legt keine Entitäten an und ändert keine. Die verwendeten vorhandenen
Entitäten wurden gegen die lokale Registry und die CSV-Zuordnungen geprüft;
es sind keine neuen CSV-Einträge erforderlich. Neue Bedienelemente werden bei
Bedarf explizit in der jeweiligen Ansicht ergänzt.
Die unten beschriebene iPhone-Ergänzung verwendet dagegen einen eigenen
Template-Sensor mit einem Eintrag in `area_assignments.csv`.

Das Garagentor wird ausdrücklich über einen bestätigten **Impuls** bedient,
weil die vorhandene Hardware Öffnen, Schließen und Stoppen mit demselben
Impuls auslöst. Die Warn-Helper sind reine Statusanzeigen. Fehlende oder
veraltete Beobachtungen werden entsprechend benannt; eine Freigabe in der
Klimasicht bedeutet nicht, dass eine Fahrt bereits erfolgt oder eingeplant ist.

## Lokal prüfen

```sh
./devscripts/configcheck.sh
docker run --rm -v "$PWD:/config:ro" ghcr.io/home-assistant/home-assistant:stable \
  python /config/tools/tests/test_home_dashboard.py
git diff --check
```

Der Template-Test verwendet eine isolierte HA-Testumgebung mit künstlichen
Zuständen und ohne laufende Integrationen oder Serviceaufrufe. Eine Prüfung
des gerenderten Dashboards auf dem HA-Server ist darin nicht enthalten.

Die Veröffentlichung erfolgt wie im übrigen Repository durch Commit und Push;
der vorhandene Server-Workflow übernimmt die Konfiguration automatisch.

Grundlage für die additive Registrierung:
[Home Assistant: zusätzliche YAML-Dashboards bei einer Storage-Hauptansicht](https://www.home-assistant.io/dashboards/dashboards/#adding-yaml-dashboards).

## iPhone: Home-Bildschirm und Sperrbildschirm

`virtual/iphone_widgets.yaml` wird über die bestehende Paketkonfiguration
geladen. Der Sensor `sensor.iphone_hausstatus` (Unique-ID `iphone_hausstatus`,
Bereich Technik) liefert seinen Hinweis als Zustand sowie drei Textattribute:

- `upper_text`: wichtigster Hinweis in der Reihenfolge Garage offen bei Regen,
  Garage offen, Boost-Warnung, Entfeuchtungswarnung, Jalousie-Automatik aus.
  Ohne Hinweis: „Keine wichtigen Hinweise“. Fehlende Statusquellen ergeben
  „Status unvollständig“, sofern kein bekannter Hinweis Vorrang hat.
- `lower_text`: Garagenfeuchte und Garagentemperatur.
- `details_text`: Außentemperatur und Regenstatus.

Die Formulierung liegt zentral in `custom_templates/iphone_widgets.jinja`.
Fehlende Messwerte werden nicht als null oder Entwarnung ausgegeben; weiterhin
vorhandene Werte bleiben sichtbar. Manuelle Jalousiesperren und Schlafmodus
gehören nicht zur Sperrbildschirm-Zusammenfassung. Der Sensor beobachtet nur
vorhandene Entitäten und löst keine Aktionen aus.

### Home-Bildschirm

In der Companion-App unter **Einstellungen → Companion-App → Widgets → Widget
erstellen** ein Custom-Widget „Mein Zuhause“ anlegen. Diese Einträge in der
angegebenen Reihenfolge hinzufügen:

| Anzeigename | Entität | Navigationsziel |
|---|---|---|
| Garagentor | `cover.aussenbereich_garage_garagentor` | `/mein-zuhause/garage` |
| Garagenfeuchte | `sensor.wifi_smart_switch_humidity` | `/mein-zuhause/garage` |
| TTK | `sensor.entfeuchter_power` | `/mein-zuhause/garage` |
| TTR-Boost | `sensor.ttr_57_entfeuchter_leistung` | `/mein-zuhause/garage` |
| Außentemperatur | `sensor.aussenbereich_wetterstation_temperatur` | `/mein-zuhause/zuhause` |
| Jalousie-Automatik | `switch.hitzeschutz_og_automatik` | `/mein-zuhause/sonne` |

Für jeden Eintrag **Tap behavior** und **Icon tap behavior** auf **Navigate**
setzen und denselben jeweiligen Pfad eintragen. Damit öffnet auch ein Tippen
auf das Tor- oder Schalter-Icon nur die Detailansicht.

Auf dem iPhone-Home-Bildschirm lange drücken → **Bearbeiten → Widget hinzufügen
→ Home Assistant → Custom**, mittlere Größe. Unter **Widget bearbeiten** das
Widget „Mein Zuhause“ auswählen. **Show states** und **Show last update time**
einschalten. Die Bezeichnungen können je nach App-Sprache übersetzt sein.

### Sperrbildschirm

Nach Veröffentlichung und automatischer Server-Übernahme zunächst prüfen,
ob `sensor.iphone_hausstatus` in der App auffindbar ist. Dann den
iPhone-Sperrbildschirm lange drücken → **Anpassen → Sperrbildschirm → Widgets
hinzufügen → Home Assistant → Details**, rechteckige Variante.

Das hinzugefügte Widget antippen, den passenden Server wählen (falls angeboten)
und **Source = Template** einstellen. Dafür muss der in der Companion-App
verwendete HA-Account Administrator sein. Die drei Felder erhalten nur diese
kurzen Verweise; die eigentliche Logik bleibt in HA:

**Upper Text Template**

```jinja
{{ state_attr('sensor.iphone_hausstatus', 'upper_text') | default('Status nicht verfügbar', true) }}
```

**Lower Text Template**

```jinja
{{ state_attr('sensor.iphone_hausstatus', 'lower_text') | default('Garage: Daten fehlen', true) }}
```

**Details Text Template**

```jinja
{{ state_attr('sensor.iphone_hausstatus', 'details_text') | default('Wetter: Daten fehlen', true) }}
```

**Run Script** ausgeschaltet lassen und die Sperrbildschirm-Anpassung speichern.
Der dritte Text wird nur in der rechteckigen Variante angezeigt.

Beispiel bei verfügbaren Messwerten und ohne Hinweis:

```text
Keine wichtigen Hinweise
Garage · 59 % · 14,2 °C
Außen · 9,4 °C · kein Regen
```

iOS bestimmt die Aktualisierung der Widgets; es handelt sich nicht um eine
Echtzeitanzeige. Es wird keine zusätzliche Push-Automation eingerichtet.
Die bestehenden Garagenwarnungen bleiben die zeitnahen Benachrichtigungen.
Widget-Platzierung und Darstellung auf dem Gerät müssen dort geprüft werden.

Die zusätzliche lokale Prüfung testet auch, dass HA die Attribute nach
Quelländerungen aktualisiert, wenn der Sensorzustand gleich bleibt:

```sh
docker run --rm -v "$PWD:/config:ro" ghcr.io/home-assistant/home-assistant:stable \
  python /config/tools/tests/test_iphone_widgets.py
```

Offizielle Grundlage: [Companion-App: iOS-Widgets](https://companion.home-assistant.io/docs/integrations/ios-widgets/).
