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
Es werden keine Entitäten angelegt oder geändert. Die verwendeten vorhandenen
Entitäten wurden gegen die lokale Registry und die CSV-Zuordnungen geprüft;
es sind keine neuen CSV-Einträge erforderlich. Neue Bedienelemente werden bei
Bedarf explizit in der jeweiligen Ansicht ergänzt.

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
