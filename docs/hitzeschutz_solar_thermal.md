# Jalousien: Solarwärme und Überhitzungsschutz

Die Testversion erzeugt echte Fahrbefehle über die bestehenden Jalousien-Scripts.
Sie ist nach Einspielen und Neustart von Home Assistant aktiv. Lokale Prüfungen
aktivieren keine Geräte. Kühlungsverschattung, Fassadenrichtungen, bestehende
Entity-IDs und Unique-IDs bleiben erhalten.

## Heizbetrieb

`binary_sensor.heizen_kuehlen_rueckmeldung = on` aktiviert die Raumregelung.
Ist- und aktive Solltemperatur stammen aus den vorhandenen KNX-Rückmeldungen.
Der Thermik-Sensor wertet jede Minute zehn Thermostat-Messstellen aus. Die beiden
Arbeitszimmer-Messstellen beziehen sich auf dieselben Fenster; beide müssen
verfügbar sein, und jede kann eine solare Öffnung verhindern.

- Überhitzungsschutz ab Soll + 0,3 K bei kalter Außenluft. Zwischen Außen =
  Soll − 5 K und Außen = Soll sinkt dieser Puffer linear auf 0,1 K.
  Fehlende Außenwerte verwenden den vorsichtigeren Puffer von 0,1 K.
- Zusätzlich lineare Regression aus bis zu 30 Minuten Minutenwerten. Erst nach
  mindestens 20 Minuten und zehn Werten wird 30 Minuten vorausgerechnet.
  Nur positive Steigungen ab 0,1 K/h lösen vorausschauenden Schutz aus;
  die verwendete Steigung ist auf 2 K/h begrenzt.
- Der Schutz bleibt eingerastet, bis Ist ≤ Soll − 0,3 K und die Vorschau ≤ Soll
  ist. Bei einer Sollwertänderung beginnt die Trendmessung neu.
- Besonnte und warme Räume verschatten nach zwei Minuten stabiler Anforderung.
  Solare Öffnungen warten zehn Minuten. Schwache Sonne gibt nach 30 Minuten frei;
  wenn die Fassade geometrisch keine Sonne mehr erhält, entfällt diese Wartezeit.
- Die bisherige Luxbewertung kann weiterhin Überhitzungsverschattung auslösen,
  auch wenn der neue Clear-Sky-Indikator unter seiner Schwelle liegt.
- Ohne Sonne auf der Fassade wird tagsüber für Tageslicht geöffnet. Die neue
  Heizregelung öffnet nicht nach Sonnenuntergang.
- Fehlende oder über 90 Minuten nicht aktualisierte Ist-/Helligkeitswerte lösen
  keine solare Öffnung aus. Konstante Sollwerte dürfen älter sein. Fehlt ein
  belastbarer Trend, bleibt der Schutz anhand der aktuellen Temperatur aktiv.

Diese Parameter sind Startwerte für den realen Test. Die Vorschau ist keine
Berechnung der Gebäudewärmebilanz. Ein Sensorwert kann innerhalb der letzten
90 Minuten unverändert geblieben sein; das Zeitlimit ersetzt keine Geräte-
Erreichbarkeitsüberwachung.

## Sonnenindikator

`sensor.hitzeschutz_clear_sky_index` berechnet lokal den Quotienten aus gemessenen
Lux und kalibrierten erwarteten Lux bei klarem Himmel. Referenz: Haurwitz-
Horizontalstrahlung aus aktueller Sonnenhöhe, skaliert mit **141,907197 lx/(W/m²)**.
Der Index ist auf 0–2 begrenzt und unter 5° Sonnenhöhe nicht verfügbar. In diesem
Bereich greifen für die Sonnenfreigabe die vorhandenen korrigierten Luxschwellen.
Bei höherer Sonne: Index ≥ 0,6 und korrigierte Lux ≥ 10.000 aktivieren das
Sonnensignal; Index < 0,45 oder korrigierte Lux < 7.000 geben es wieder frei.

Für die Kalibrierung wurden Recorder-Stundenmittel mit öffentlichen Open-Meteo-
ERA5-Daten für die konfigurierte Position Wiesbaden-Sonnenberg abgeglichen.
Strahlungswerte zum Wetterzeitpunkt t beziehen sich auf die vorhergehende Stunde;
sie werden deshalb mit Recorder-Startzeit t − 1 h verbunden. Die Auswahl klarer
Stunden verwendet Bewölkung ≤ 20 % und Direktnormalstrahlung ≥ 400 W/m².

Von 1.682 passenden Tagesstunden im Gesamtzeitraum Mai–Oktober waren 371 klar.
Der starke saisonale Unterschied verbietet einen gemeinsamen Jahresfaktor.
Verwendet werden **57 klare Herbststunden vom 1. September bis 4. Oktober**.
Eine zeitlich getrennte Prüfung und die saisonalen Unterschiede stehen in
[hitzeschutz_solar_kalibrierung.json](hitzeschutz_solar_kalibrierung.json).

ERA5 liefert modellierte Rasterdaten; die nächste Rasterzelle liegt bei
50,00° N / 8,25° E. Der Luxquotient ist ein Sonnenindikator, keine gemessene
Strahlungsleistung und kein Bewölkungsgrad in Prozent. Winterdaten fehlen bislang.
Die Wärmeentscheidung hängt deshalb zusätzlich von Raumtemperatur und Trend ab.
Im laufenden Betrieb sind weder externe Wetterabfragen noch zusätzliche Pakete nötig.

Reproduzierbare Kalibrierung mit lokalem Recorder-Snapshot und öffentlichem Abruf:

```sh
python3 tools/calibrate_solar_lux.py --fetch --weather-json /tmp/solar-weather.json
```

## Fahrbefehle und vorhandene Sperren

18 Jalousien sind Thermostaten zugeordnet. Flur OG und Treppe OG verwenden auf
ausdrücklichen Wunsch die Ist-/Solltemperatur und den Temperaturtrend des
Schlafzimmers. Ihre eigenen Fassadenrichtungen und physischen Raumzuordnungen
bleiben erhalten. WC OG und Sonnensegel verwenden weiterhin die vorhandenen
Regeln. Die Zuordnungen wurden gegen `area_assignments.csv` geprüft; die beiden
bewussten Verknüpfungen über Raumgrenzen sind dort dokumentiert.

Alle normalen Fahrbefehle laufen pro Jalousie durch
`script.hitzeschutz_jalousie_automatisieren`. Fassaden- und Sammel-Scripts
verteilen nur die Aufrufe; die Rueckmeldung des zentralen Scripts bestimmt,
ob eine Fahrt als ausgeloest gemeldet wird. Die gemeinsame Funktion
`cover_automation_status` in `custom_templates/cover_control.jinja` prueft
Position, Bewegungsrichtung, Automatik-Schalter, Automatik-Gruppe, OG-Zeitgrenze,
Fernseher, Heiz-/Kuehlmodus, thermische Freigabe und manuelle Sperre.
Die Planung verwendet dieselbe Funktion. Im Warteschlangen-Script erfolgt die
Pruefung erst bei Ausfuehrung, damit zwischenzeitliche manuelle Bedienung auch
bereits eingeplante Fahrten verhindert.

Der stuendliche Schliess-Nachcheck setzt `recheck_closed: true`: An weiterhin
aktiven Fassaden wird der Schliessbefehl auch bei gemeldeter geschlossener
Endlage wiederholt. Anlass waren am 29.10.2026 physisch offene Aussenrolllaeden
(Schlafzimmer Panorama und Bad Balkon), die HA und KNX bereits als geschlossen
meldeten und die auf einen erneuten Schliessbefehl herunterfuhren. Die Ursache
der abweichenden Aktor-Rueckmeldung ist damit noch nicht geklaert. Die Wiederholung
umgeht ausschliesslich die Positionspruefung fuer das Schliessen; Bewegung,
Verfuegbarkeit, manuelle Sperren, Automatik-, TV- und Thermikfreigaben bleiben
wirksam. Minuetliche Regelung und Oeffnungsbefehle wiederholen keine bereits
erreichten Ziele. Eine Aktor-Rueckmeldung ersetzt keine physische Kontrolle.

`cover_manual_blocked` in `custom_templates/manual_control.jinja` liefert die
zentrale vierstuendige manuelle Sperre pro Jalousie. Fehlender Sperrstatus
verhindert normale Automatikfahrten. Manuelle eingehende KNX-Telegramme,
HomeKit-Befehle und Cover-Serviceaufrufe mit Benutzerkontext werden auch waehrend
laufender Automatikfahrten erfasst. Eigene KNX-Telegramme werden anhand von
Richtung und Quelle, eigene Serviceaufrufe anhand des fehlenden Benutzerkontexts
unterschieden. Bei benutzergestarteten Automatik-Scripts werden eigene
Serviceaufrufe am Kontext des laufenden zentralen Jalousien-Scripts erkannt.
Die generierte Zuordnung `related_covers` verbindet virtuelle Sammeljalousien
mit ihren Einzeljalousien, damit eine manuelle Sperre nicht ueber einen anderen
Zugriff auf denselben Antrieb umgangen wird. Der alte globale Fahrbefehl-Helper bleibt als ungenutzte
Kompatibilitaets-Entity erhalten; er darf keine manuellen Ereignisse ausblenden.
Der ausdrueckliche Aufruf von `auto_jalousien` setzt weiterhin die manuellen
Sperren zurueck und kann Automatik-Schalter, Gruppenmarkierung und TV-Sperre
uebergehen. Die OG-Zeitgrenze und die thermische Freigabe gelten weiterhin.

Die minuetliche Regelung ueberspringt blockierte oder bereits bewegte Jalousien
vor der Sammelpruefung. Im Kuehlmodus wirken die vorhandenen Fassadenregeln;
ein Wechsel auf Kuehlen loest zusaetzlich einen Nachcheck aus.

## Prüfung und Auswertung des realen Tests

```sh
./devscripts/configcheck.sh
docker run --rm -v "$PWD:/config:ro" ghcr.io/home-assistant/home-assistant:stable \
  python /config/tools/tests/test_solar_thermal.py
git diff --check
```

Die Verhaltenstests laufen ohne Live-Integrationen, mit temporären Registries.
Sie prüfen Temperaturhysterese, Vorschau, Wolkenwechsel, fehlende Werte,
Moduswechsel, Sperren, Schutz vor konkurrierenden Fassadenbefehlen und CSV-Metadaten.
Sie beweisen weder reale Raumtemperaturverläufe noch die erfolgte Aktivierung.

Nach Aktivierung enthalten die Attribute von `sensor.hitzeschutz_thermik` pro
Raum Temperatur, Sollwert, Trend, Vorschau und thermische Sperre. Pro Jalousie
stehen gewünschte Fahrt, Grund und Wartezeitbeginn zur Verfügung. Im Recorder
lassen sich diese Entscheidungen zusammen mit echten Temperaturen und tatsächlichen
Cover-/KNX-Fahrten auswerten. Die erste Kontrolle sollte gespeicherten Zustand,
ausgelöste Fahrten und den Verlauf über sonnige Stunden gemeinsam betrachten.

Rücknahme: `virtual/solar_thermal.yaml` und `custom_templates/solar_thermal.jinja`
entfernen, die Änderungen an `scripts.yaml` sowie die vier neuen CSV-Zeilen
zurücknehmen, anschließend prüfen und Home Assistant neu starten. Die bestehenden
Automationen in `automations.yaml` wurden nicht verändert.
