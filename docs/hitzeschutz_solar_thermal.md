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

Alle normalen Fahrbefehle respektieren Automatik-Schalter, Automatik-Gruppe,
manuellen Override von vier Stunden, TV-Sperre und OG-Öffnung erst ab 10 Uhr.
Auch das bestehende Script „Auto Jalousien“ berücksichtigt die Wärmeentscheidung;
seine ausdrücklichen Ausnahmen für die anderen Sperren bleiben erhalten.

Die Fahrbefehle werden nacheinander ausgeführt, damit das gemeinsame Kennzeichen
für Automatikfahrten während der fünf Sekunden Nachlauf nicht durch eine andere
Fahrt vorzeitig gelöscht wird. Direkt vor der Fahrt werden Sperren, Position,
Wärmeentscheidung und unveränderter Heiz-/Kühlmodus erneut geprüft. Die minütliche
Regelung überspringt blockierte oder bereits bewegte Jalousien ohne wiederholte
Benachrichtigung. Im Kühlmodus wirken weiter die vorhandenen Fassadenregeln;
ein Wechsel auf Kühlen löst zusätzlich einen Nachcheck aus.

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
