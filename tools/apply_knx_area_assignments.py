#!/usr/bin/env python3
"""
Home-Assistant-Räume/Stockwerke für die konvertierten KNX-Entitäten anwenden.

Vorgehen:
  1. Home Assistant Core stoppen, damit .storage-Dateien nicht parallel geschrieben werden.
  2. Dieses Skript im Repository oder in /config ausführen:
       python3 tools/apply_knx_area_assignments.py --config-dir /config
  3. Home Assistant Core wieder starten.

Das Skript erzeugt Sicherungskopien der geänderten .storage-Dateien.
"""
from __future__ import annotations
import argparse, csv, json, shutil, sys
from pathlib import Path
from datetime import datetime, timezone

FLOOR_VERSION = 1
FLOOR_MINOR_VERSION = 3
AREA_VERSION = 1
AREA_MINOR_VERSION = 9


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def legacy_entity_ids(row: dict[str, str]) -> list[str]:
    notes = row.get('notes') or ''
    marker = 'legacy_entity_ids='
    if marker not in notes:
        return []
    raw = notes.split(marker, 1)[1].split()[0]
    return [item for item in raw.split(';') if item]


def desired_hidden_by(row: dict[str, str]) -> str | None:
    notes = row.get('notes') or ''
    marker = 'hidden_by='
    if marker not in notes:
        return None
    value = notes.split(marker, 1)[1].split()[0]
    if value == 'none':
        return ''
    return value


def desired_device_area(row: dict[str, str]) -> str | None:
    notes = row.get('notes') or ''
    marker = 'device_area='
    if marker in notes:
        value = notes.split(marker, 1)[1].split()[0]
        if value == 'none':
            return None
        return value
    return row['area_id']


def backup(path: Path) -> None:
    if path.exists():
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        shutil.copy2(path, path.with_name(path.name + f'.bak-{stamp}'))


def load_store(path: Path, key: str, version: int, minor_version: int, data_key: str) -> dict:
    if path.exists():
        with path.open(encoding='utf-8') as f:
            return json.load(f)
    return {
        'version': version,
        'minor_version': minor_version,
        'key': key,
        'data': {data_key: []},
    }


def write_store(path: Path, data: dict, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    backup(path)
    with path.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')


def upsert_floors(storage: Path, floors_csv: Path, dry_run: bool) -> tuple[int, int]:
    rows = load_csv(floors_csv)
    path = storage / 'core.floor_registry'
    store = load_store(path, 'core.floor_registry', FLOOR_VERSION, FLOOR_MINOR_VERSION, 'floors')
    store.setdefault('data', {}).setdefault('floors', [])
    by_id = {f['floor_id']: f for f in store['data']['floors']}
    created = updated = 0
    t = now_iso()
    for r in rows:
        aliases = [a for a in r.get('aliases','').split(';') if a]
        level = int(r['level']) if r.get('level') else None
        if r['floor_id'] in by_id:
            f = by_id[r['floor_id']]
            before = dict(f)
            f.update({'aliases': aliases, 'icon': f.get('icon'), 'level': level, 'name': r['name']})
            if f != before:
                f['modified_at'] = t
                updated += 1
        else:
            store['data']['floors'].append({
                'aliases': aliases,
                'floor_id': r['floor_id'],
                'icon': None,
                'level': level,
                'name': r['name'],
                'created_at': t,
                'modified_at': t,
            })
            created += 1
    write_store(path, store, dry_run)
    return created, updated


def upsert_areas(storage: Path, areas_csv: Path, dry_run: bool) -> tuple[int, int]:
    rows = load_csv(areas_csv)
    path = storage / 'core.area_registry'
    store = load_store(path, 'core.area_registry', AREA_VERSION, AREA_MINOR_VERSION, 'areas')
    store.setdefault('data', {}).setdefault('areas', [])
    by_id = {a['id']: a for a in store['data']['areas']}
    created = updated = 0
    t = now_iso()
    for r in rows:
        aliases = [a for a in r.get('aliases','').split(';') if a]
        floor_id = r.get('floor_id') or None
        if r['area_id'] in by_id:
            a = by_id[r['area_id']]
            before = dict(a)
            a.setdefault('humidity_entity_id', None)
            a.setdefault('picture', None)
            a.setdefault('temperature_entity_id', None)
            a.setdefault('labels', [])
            a.update({'aliases': aliases, 'floor_id': floor_id, 'icon': a.get('icon'), 'name': r['name']})
            if a != before:
                a['modified_at'] = t
                updated += 1
        else:
            store['data']['areas'].append({
                'aliases': aliases,
                'floor_id': floor_id,
                'humidity_entity_id': None,
                'icon': None,
                'id': r['area_id'],
                'labels': [],
                'name': r['name'],
                'picture': None,
                'temperature_entity_id': None,
                'created_at': t,
                'modified_at': t,
            })
            created += 1
    write_store(path, store, dry_run)
    return created, updated


def remove_obsolete_areas(storage: Path, obsolete_areas_csv: Path, dry_run: bool) -> tuple[int, int, int]:
    if not obsolete_areas_csv.exists():
        return 0, 0, 0
    rows = load_csv(obsolete_areas_csv)
    obsolete = {r['area_id']: r.get('replacement_area_id') or None for r in rows if r.get('area_id')}
    if not obsolete:
        return 0, 0, 0

    area_path = storage / 'core.area_registry'
    if not area_path.exists():
        return 0, 0, 0
    with area_path.open(encoding='utf-8') as f:
        area_store = json.load(f)
    areas = area_store.get('data', {}).get('areas', [])
    before_count = len(areas)
    area_store['data']['areas'] = [a for a in areas if a.get('id') not in obsolete]
    removed = before_count - len(area_store['data']['areas'])

    entity_changed = 0
    entity_path = storage / 'core.entity_registry'
    if entity_path.exists():
        with entity_path.open(encoding='utf-8') as f:
            entity_store = json.load(f)
        t = now_iso()
        for e in entity_store.get('data', {}).get('entities', []):
            area_id = e.get('area_id')
            if area_id in obsolete:
                e['area_id'] = obsolete[area_id]
                e['modified_at'] = t
                entity_changed += 1
        if entity_changed and not dry_run:
            write_store(entity_path, entity_store, dry_run=False)

    device_changed = 0
    device_path = storage / 'core.device_registry'
    if device_path.exists():
        with device_path.open(encoding='utf-8') as f:
            device_store = json.load(f)
        t = now_iso()
        for d in device_store.get('data', {}).get('devices', []):
            area_id = d.get('area_id')
            if area_id in obsolete:
                d['area_id'] = obsolete[area_id]
                d['modified_at'] = t
                device_changed += 1
        if device_changed and not dry_run:
            write_store(device_path, device_store, dry_run=False)

    if removed and not dry_run:
        write_store(area_path, area_store, dry_run=False)
    return removed, entity_changed, device_changed


def apply_entity_areas(storage: Path, assignments_csv: Path, dry_run: bool) -> tuple[int, int, int, int, list[str], dict[str, str | None]]:
    assignments = [r for r in load_csv(assignments_csv) if r.get('area_id')]
    path = storage / 'core.entity_registry'
    if not path.exists():
        return 0, 0, 0, len(assignments), ['core.entity_registry nicht gefunden; KNX-Entitäten zuerst einmal von HA anlegen lassen.'], {}
    with path.open(encoding='utf-8') as f:
        store = json.load(f)
    entities = store.get('data', {}).get('entities', [])

    # Prefer unique_id; fall back to expected entity_id.
    by_uid: dict[str, list[dict]] = {}
    by_eid: dict[str, dict] = {}
    for e in entities:
        by_eid[e.get('entity_id')] = e
        if e.get('unique_id'):
            by_uid.setdefault(e['unique_id'], []).append(e)

    changed = 0
    renamed = 0
    hidden_changed = 0
    unmatched: list[str] = []
    device_area: dict[str, str | None] = {}
    t = now_iso()
    for a in assignments:
        candidates = by_uid.get(a['unique_id'], []) if a.get('unique_id') else []
        e = None
        # If multiple candidates ever occur, prefer same domain.
        if candidates:
            expected_domain = a.get('domain')
            e = next((x for x in candidates if x.get('entity_id','').startswith(expected_domain + '.')), None)
        if e is None:
            e = by_eid.get(a.get('expected_entity_id'))
        if e is None:
            e = next((by_eid[x] for x in legacy_entity_ids(a) if x in by_eid), None)
        if e is None:
            unmatched.append(f"{a.get('domain')}.{a.get('name')} / unique_id={a.get('unique_id')} / expected={a.get('expected_entity_id')}")
            continue
        expected_entity_id = a.get('expected_entity_id')
        if expected_entity_id and e.get('entity_id') != expected_entity_id and expected_entity_id not in by_eid:
            old_entity_id = e.get('entity_id')
            e['entity_id'] = expected_entity_id
            e['modified_at'] = t
            if old_entity_id in by_eid:
                del by_eid[old_entity_id]
            by_eid[expected_entity_id] = e
            renamed += 1
        if e.get('area_id') != a['area_id']:
            e['area_id'] = a['area_id']
            e['modified_at'] = t
            changed += 1
        hidden_by = desired_hidden_by(a)
        if hidden_by is not None:
            hidden_value = hidden_by or None
            if e.get('hidden_by') != hidden_value:
                e['hidden_by'] = hidden_value
                e['modified_at'] = t
                hidden_changed += 1
        if e.get('device_id'):
            device_area[e['device_id']] = desired_device_area(a)
    if (changed or renamed or hidden_changed) and not dry_run:
        write_store(path, store, dry_run=False)
    elif dry_run:
        # no write
        pass
    return changed, renamed, hidden_changed, len(unmatched), unmatched, device_area


def apply_device_areas(storage: Path, device_area: dict[str, str | None], dry_run: bool) -> int:
    if not device_area:
        return 0
    path = storage / 'core.device_registry'
    if not path.exists():
        return 0
    with path.open(encoding='utf-8') as f:
        store = json.load(f)
    changed = 0
    t = now_iso()
    for d in store.get('data', {}).get('devices', []):
        device_id = d.get('id')
        if device_id not in device_area:
            continue
        area = device_area[device_id]
        if d.get('area_id') != area:
            d['area_id'] = area
            d['modified_at'] = t
            changed += 1
    if changed and not dry_run:
        write_store(path, store, dry_run=False)
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--config-dir', default='/config', help='Home-Assistant-Konfigurationsverzeichnis, Standard: /config')
    ap.add_argument('--data-dir', default=None, help='Verzeichnis mit floors.csv, areas.csv und area_assignments.csv; Standard: Repository-Wurzel')
    ap.add_argument('--dry-run', action='store_true', help='Nur prüfen, nichts schreiben')
    args = ap.parse_args()

    config_dir = Path(args.config_dir)
    storage = config_dir / '.storage'
    data_dir = Path(args.data_dir) if args.data_dir else Path(__file__).resolve().parents[1]
    floors_csv = data_dir / 'floors.csv'
    areas_csv = data_dir / 'areas.csv'
    assignments_csv = data_dir / 'area_assignments.csv'
    obsolete_areas_csv = data_dir / 'obsolete_areas.csv'

    for p in (floors_csv, areas_csv, assignments_csv):
        if not p.exists():
            print(f'FEHLT: {p}', file=sys.stderr)
            return 2

    fc, fu = upsert_floors(storage, floors_csv, args.dry_run)
    ac, au = upsert_areas(storage, areas_csv, args.dry_run)
    ar, ae, ad = remove_obsolete_areas(storage, obsolete_areas_csv, args.dry_run)
    ec, er, eh, missing, unmatched, device_area = apply_entity_areas(storage, assignments_csv, args.dry_run)
    dc = apply_device_areas(storage, device_area, args.dry_run)

    print(f'Floors: erstellt={fc}, aktualisiert={fu}')
    print(f'Areas: erstellt={ac}, aktualisiert={au}')
    print(f'Obsolete Areas: entfernt={ar}, Entity-Zuordnungen geändert={ae}, Device-Zuordnungen geändert={ad}')
    print(f'Entities: Area geändert={ec}, Entity-ID geändert={er}, Sichtbarkeit geändert={eh}, nicht gefunden={missing}')
    print(f'Devices: Area geändert={dc}')
    if unmatched:
        print('\nNicht zugeordnete erwartete Entitäten:')
        for item in unmatched:
            print('  - ' + item)
        print('\nDas ist normal, wenn Home Assistant nach dem YAML-Import noch nicht neu gestartet wurde oder wenn Entity-IDs manuell geändert wurden. Unique-IDs werden bevorzugt; geänderte Entity-IDs sind daher meist unkritisch.')
    if args.dry_run:
        print('\nDRY-RUN: Es wurden keine Dateien geändert.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
