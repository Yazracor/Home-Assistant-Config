#!/usr/bin/env python3
"""Generate the KNX address -> cover entity map used by heat-protection templates."""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
AREA_ASSIGNMENTS = ROOT / "area_assignments.csv"
KNX_COVERS = ROOT / "knx" / "covers.yaml"
KNX_XML = ROOT / "KNX.xml"
VIRTUAL_DIR = ROOT / "virtual"
OUTPUT = ROOT / "custom_templates" / "hitzeschutz_manual_generated.jinja"


ADDRESS_RE = re.compile(r"^\d+/\d+/\d+$")
CSV_KNX_ID_RE = re.compile(r"^(\d+/\d+/\d+)_")
YAML_FIELD_RE = re.compile(r'^\s+(name|move_long_address|move_short_address):\s+"?([^"#]+?)"?\s*$')
YAML_ADDRESS_NAME_RE = re.compile(r"^\s*#\s+move_long_address:\s+(\d+/\d+/\d+)\s+->\s+(.+?)\s+\|")
VIRTUAL_UNIQUE_ID_RE = re.compile(r"^\s+unique_id:\s+\"?([^\"\n]+)\"?\s*$")
VIRTUAL_COVER_RE = re.compile(r"^\s+-\s+(cover\.[A-Za-z0-9_]+)\s*$")


@dataclass(frozen=True)
class CoverRecord:
    entity_id: str
    name: str
    source_identifier: str
    area_slug: str
    floor_slug: str
    notes: str


def normalize(value: str) -> str:
    return (
        value.lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
        .replace(".", "")
        .replace("(", "")
        .replace(")", "")
        .strip()
    )


def read_cover_registry() -> tuple[dict[str, CoverRecord], dict[str, str], dict[str, str]]:
    covers: dict[str, CoverRecord] = {}
    address_to_entity: dict[str, str] = {}
    unique_id_to_entity: dict[str, str] = {}

    with AREA_ASSIGNMENTS.open(newline="", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            if len(row) < 4 or row[0] != "cover":
                continue

            entity_id = row[2]
            source_identifier = row[3]
            covers[entity_id] = CoverRecord(
                entity_id=entity_id,
                name=row[1],
                source_identifier=source_identifier,
                area_slug=row[4],
                floor_slug=row[6],
                notes=row[9] if len(row) > 9 else "",
            )
            unique_id_to_entity[source_identifier] = entity_id

            if match := CSV_KNX_ID_RE.match(source_identifier):
                address_to_entity[match.group(1)] = entity_id

    return covers, address_to_entity, unique_id_to_entity


def read_knx_cover_addresses(address_to_entity: dict[str, str]) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    knx_map: dict[str, set[str]] = defaultdict(set)
    entity_addresses: dict[str, set[str]] = defaultdict(set)
    entity_labels: dict[str, set[str]] = defaultdict(set)
    address_labels: dict[str, str] = {}
    current: dict[str, str] = {}

    def flush() -> None:
        move_long = current.get("move_long_address")
        if not move_long:
            return

        entity_id = address_to_entity.get(move_long)
        if not entity_id:
            return

        for key in ("move_long_address", "move_short_address"):
            address = current.get(key)
            if address and ADDRESS_RE.match(address):
                knx_map[address].add(entity_id)
                entity_addresses[entity_id].add(address)
                if label := address_labels.get(move_long):
                    entity_labels[entity_id].add(label)

    with KNX_COVERS.open(encoding="utf-8") as yamlfile:
        for line in yamlfile:
            if line.startswith("- name:"):
                flush()
                current = {}

            if match := YAML_ADDRESS_NAME_RE.match(line):
                address_labels[match.group(1)] = normalize(match.group(2))

            if match := YAML_FIELD_RE.match(line):
                current[match.group(1)] = match.group(2).strip()

    flush()
    return knx_map, entity_addresses, entity_labels


def add_virtual_cover_addresses(
    knx_map: dict[str, set[str]],
    entity_addresses: dict[str, set[str]],
    unique_id_to_entity: dict[str, str],
) -> None:
    for path in sorted(VIRTUAL_DIR.glob("*.yaml")):
        unique_id = ""
        target_entities: set[str] = set()

        for line in path.read_text(encoding="utf-8").splitlines():
            if match := VIRTUAL_UNIQUE_ID_RE.match(line):
                if unique_id:
                    add_virtual_cover(unique_id, target_entities, knx_map, entity_addresses, unique_id_to_entity)
                unique_id = match.group(1).strip()
                target_entities = set()
                continue

            if unique_id and (match := VIRTUAL_COVER_RE.match(line)):
                target_entities.add(match.group(1))

        if unique_id:
            add_virtual_cover(unique_id, target_entities, knx_map, entity_addresses, unique_id_to_entity)


def add_virtual_cover(
    unique_id: str,
    target_entities: set[str],
    knx_map: dict[str, set[str]],
    entity_addresses: dict[str, set[str]],
    unique_id_to_entity: dict[str, str],
) -> None:
    virtual_entity = unique_id_to_entity.get(unique_id)
    if not virtual_entity:
        return

    for target_entity in target_entities:
        for address in entity_addresses.get(target_entity, set()):
            knx_map[address].add(virtual_entity)


def add_central_addresses(
    knx_map: dict[str, set[str]],
    covers: dict[str, CoverRecord],
    entity_labels: dict[str, set[str]],
) -> None:
    for element in ElementTree.parse(KNX_XML).iter():
        if element.tag.rsplit("}", 1)[-1] != "GroupAddress":
            continue
        address = element.attrib.get("Address", "")
        name = element.attrib.get("Name", "").strip()
        if not ADDRESS_RE.match(address) or not is_blind_group_address(name, address):
            continue

        entities = infer_central_entities(name, covers, entity_labels)
        if entities:
            knx_map[address].update(entities)


def is_blind_group_address(name: str, address: str) -> bool:
    normalized = normalize(name)
    if not (normalized.endswith(" lz") or normalized.endswith(" kz")):
        return False
    if address.startswith("1/2/"):
        return "jalousie" in normalized
    return (
        "zentral" in normalized
        or "x" in normalized
        or "treppe+flur" in normalized
    )


def infer_central_entities(
    name: str,
    covers: dict[str, CoverRecord],
    entity_labels: dict[str, set[str]],
) -> set[str]:
    normalized = normalize(name)

    if "innenjalousien zentral og" in normalized:
        return matching_covers(covers, indoor=True, floor_slug="obergeschoss")

    if "jalousie zentral aussen" in normalized:
        return matching_covers(covers, indoor=False)
    if "jalousie zentral eg" in normalized:
        return matching_covers(covers, indoor=False, floor_slug="erdgeschoss")
    if "jalousie zentral og" in normalized:
        return matching_covers(covers, indoor=False, floor_slug="obergeschoss")
    if "jalousie zentral kg" in normalized:
        return matching_covers(covers, indoor=False, floor_slug="kellergeschoss")

    if "kg kind zentral" in normalized:
        return matching_covers(covers, floor_slug="kellergeschoss")
    if "eg kueche 3x" in normalized:
        return matching_covers(covers, area_slug="kueche")
    if "eg wohnz 2x" in normalized:
        return matching_covers(covers, area_slug="wohnzimmer")
    if "eg gast zentral" in normalized:
        return matching_covers(covers, area_slug="arbeitszimmer") | {
            entity_id
            for entity_id, labels in entity_labels.items()
            if any("eg gast" in label for label in labels)
        }

    if "og schlafz" in normalized and "aussen" in normalized and "4x" in normalized.replace(" ", ""):
        return matching_covers(covers, area_slug="schlafzimmer", indoor=False)
    if "og schlafz" in normalized and "innen" in normalized and "4x" in normalized.replace(" ", ""):
        return matching_covers(covers, area_slug="schlafzimmer", indoor=True)
    if "og bad" in normalized and "aussen" in normalized:
        return matching_covers(covers, area_slug="bad_og", indoor=False)
    if "treppe+flur" in normalized:
        return matching_covers(covers, area_slug="flur_og") | matching_covers(covers, area_slug="treppe_og")

    return set()


def matching_covers(
    covers: dict[str, CoverRecord],
    *,
    area_slug: str | None = None,
    floor_slug: str | None = None,
    indoor: bool | None = None,
) -> set[str]:
    entities: set[str] = set()
    for record in covers.values():
        if record.entity_id == "cover.aussenbereich_garage_garagentor":
            continue
        if area_slug and record.area_slug != area_slug:
            continue
        if floor_slug and record.floor_slug != floor_slug:
            continue
        if indoor is not None and is_indoor_cover(record) != indoor:
            continue
        entities.add(record.entity_id)
    return entities


def is_indoor_cover(record: CoverRecord) -> bool:
    text = normalize(" ".join([record.entity_id, record.name]))
    return "innen" in text


def sort_address(address: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in address.split("/"))


def render(knx_map: dict[str, set[str]]) -> str:
    lines = [
        "{#",
        "  Generated by tools/generate_hitzeschutz_manual_map.py.",
        "  Sources: knx/covers.yaml, KNX.xml, virtual/*.yaml, area_assignments.csv.",
        "  Do not edit manually.",
        "#}",
        "{% macro knx_cover_map(returns) %}",
        "  {% do returns({",
    ]

    addresses = sorted(knx_map, key=sort_address)
    for index, address in enumerate(addresses):
        entities = ", ".join(f"'{entity}'" for entity in sorted(knx_map[address]))
        comma = "," if index < len(addresses) - 1 else ""
        lines.append(f"    '{address}': [{entities}]{comma}")

    lines.extend([
        "  }) %}",
        "{% endmacro %}",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    covers, address_to_entity, unique_id_to_entity = read_cover_registry()
    knx_map, entity_addresses, entity_labels = read_knx_cover_addresses(address_to_entity)
    add_virtual_cover_addresses(knx_map, entity_addresses, unique_id_to_entity)
    add_central_addresses(knx_map, covers, entity_labels)
    OUTPUT.write_text(render(knx_map), encoding="utf-8")


if __name__ == "__main__":
    main()
