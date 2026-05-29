# Räume und Stockwerke für die KNX-Migration

Dieses Paket ergänzt die funktionierende KNX-YAML-Konfiguration um Home-Assistant-Räume und Stockwerke.

Wichtig: Die KNX-YAML selbst enthält keine Raum-/Stockwerkzuordnung. Home Assistant speichert diese Zuordnung in `.storage/core.area_registry`, `.storage/core.floor_registry` und für Entitäten in `.storage/core.entity_registry`.

## Stockwerke

| Stockwerk | ID | Level | Aliase |
|---|---:|---:|---|
| Obergeschoss | `obergeschoss` | 1 | OG |
| Erdgeschoss | `erdgeschoss` | 0 | EG |
| Kellergeschoss | `kellergeschoss` | -1 | KG;Keller |
| Außenbereich | `aussenbereich` | — | Aussen;Außen;Draußen |

## Räume / Areas

| Stockwerk | Raum | Area-ID | Anzahl zugeordneter KNX-Entitäten | Aliase |
|---|---|---:|---:|---|
| Erdgeschoss | Arbeitszimmer | `arbeitszimmer` | 10 | Buero;Büro EG;EG Büro;Gastzimmer;EG Gast |
| Erdgeschoss | Gästebad | `gaestebad` | 1 | Buero.Bad;EG Gästebad |
| Erdgeschoss | Flur EG | `flur_eg` | 2 | EG_Flur;Diele;Galerie |
| Erdgeschoss | Treppe EG/KG | `treppe_eg_kg` | 1 | EG_UG_Treppe;EG/KG Treppe |
| Erdgeschoss | Gäste-WC | `gaeste_wc` | 1 | EG_GaesteWC;EG WC |
| Erdgeschoss | Garderobe | `garderobe` | 2 | EG_Garderobe;Schuhschrank |
| Erdgeschoss | Küche | `kueche` | 4 | Kueche;Kochen;EG Küche;Esszimmer |
| Erdgeschoss | Wohnzimmer | `wohnzimmer` | 4 | Wohnz;Wohnzimmer |
| Erdgeschoss | Vorratsraum | `vorratsraum` | 1 | EG_Vorratsraum;Vorrat |
| Obergeschoss | Büro OG | `buero_og` | 2 | Buero_OG;OG Arbeiten;OG_Arbeiten |
| Obergeschoss | Flur OG | `flur_og` | 2 | OG_Flur |
| Obergeschoss | Treppe OG | `treppe_og` | 2 | OG_Treppe |
| Obergeschoss | Schlafzimmer | `schlafzimmer` | 7 | Schlafzimmer_hidden;OG Schlafzimmer |
| Obergeschoss | Ankleide | `ankleide` | 2 | Ankleide;Umkleide;OG_Umkleide |
| Obergeschoss | Bad OG | `bad_og` | 5 | OG_Bad;OG Bad;Waschen |
| Obergeschoss | WC OG | `wc_og` | 2 | OG_WC;OG WC |
| Kellergeschoss | Sauna | `sauna` | 1 | KG_Sauna |
| Kellergeschoss | Gast/Hobby | `gast_hobby` | 1 | KG_Gast;Gast;Hobby |
| Kellergeschoss | Zimmer Sinja | `zimmer_sinja` | 1 | KG_Sinja;Kind 1 |
| Kellergeschoss | Zimmer Silas | `zimmer_silas` | 1 | KG_Silas;Kind 2 |
| Kellergeschoss | Flur KG | `flur_kg` | 1 | KG_Flur |
| Kellergeschoss | Kinderbad | `kinderbad` | 1 | KG_Kinderbad;Bad Kinder |
| Kellergeschoss | Waschküche | `waschkueche` | 1 | KG_Waschkueche;Waschküche |
| Kellergeschoss | Keller | `keller` | 4 | KG_Keller;UV-Raum;Keller klein;Keller vorn;Keller hinten |
| Außenbereich | Balkon | `balkon` | 1 | Sonnensegel;Balkon;Terrasse EG |
| Außenbereich | Balkon Obergeschoss | `balkon_obergeschoss` | 1 | Aussenbeleuchtung OG;Balkon Obergeschoss |
| Außenbereich | Terrasse | `terrasse` | 1 | Terrasse;Terrasse KG |
| Außenbereich | Garage | `garage` | 2 | Garagentuer;Garagentor;Garage Innen |
| Außenbereich | Eingangsbereich | `eingangsbereich` | 1 | Eingang;Vorgarten;Eingang Vordach;Treppe und Garage;Hof Bega Baumstrahler |
| Außenbereich | Teich | `teich` | 2 | Teich;Licht Teich;Unterwasserstrahler |
| Außenbereich | Garten | `garten` | 3 | Garten;Aussenleuchten links;Aussenleuchten rechts;Wegebeleuchtung nach oben;Wegebeleuchtung nach unten |
| Außenbereich | Wetterstation | `wetterstation` | 5 | Wetter;Windwächter;Windwaechter |

## Bewusst getroffene Zuordnungen

- `Buero.Decke`, `TH_EG_Buero`, `Buero.Flur` und die beiden Büro-Fensterjalousien liegen in `Arbeitszimmer`, weil die bereits vorhandene KNX-Panel-Entität `light.arbeitszimmer_decke` diese Semantik vorgibt.
- `Buero.Bad` liegt in `Gästebad`, weil die ETS-Gruppenadresse `EG Gästebad` nennt.
- `Esszimmer.Decke_Kochen` liegt in `Küche`, weil Esszimmer und Küche ein gemeinsamer Raum sind und die ETS-Gruppenadressen `EG Küche Decke` nennen.
- `Jalousie_EG_Kueche_Sonnensegel` liegt in `Balkon`, weil das physisch Außenbereich ist, obwohl FHEM den Raum `Kueche` verwendet.
- Die Treppe ist in `Treppe OG` und `Treppe EG/KG` getrennt, weil Home Assistant Areas jeweils nur einem Stockwerk zugeordnet werden können.

## Anwendung

Variante mit Skript, empfohlen:

```bash
ha core stop
python3 /config/tools/apply_knx_area_assignments.py --config-dir /config
ha core start
```

Wenn das Skript aus einem anderen Verzeichnis gestartet wird:

```bash
python3 tools/apply_knx_area_assignments.py --config-dir /config --data-dir /config
```

Vorher prüfen, ohne zu schreiben:

```bash
python3 tools/apply_knx_area_assignments.py --config-dir /config --dry-run
```

Das Skript legt Sicherungskopien der geänderten `.storage`-Dateien an.

## Dateien

- `floors.csv` – Ziel-Stockwerke
- `areas.csv` – Ziel-Räume / Areas
- `area_assignments.csv` – Zuordnung der KNX-Entitäten zu Areas
- `.storage/core.floor_registry` und `.storage/core.area_registry` – fertige Registry-Vorlagen für leere Installationen
- `tools/apply_knx_area_assignments.py` – Merge-/Patch-Skript für `.storage`
