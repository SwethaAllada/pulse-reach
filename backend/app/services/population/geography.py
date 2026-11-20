"""Geographic hierarchy derived from existing reference and record labels (no invented places).

country `AE` -> state `AE-AZ` (Abu Dhabi Emirate, ISO 3166-2) -> district `AE-AZ-<region_code>`
(the three official regions) -> local area `AE-AZ-<code>-L-<slug>` (patient `district_label`)
and city `AE-AZ-<code>-C-<slug>` (published SDI facility `city` label; facility-only).

Containment of a local area or city inside its region is by record (the record states the
region); there is no boundary geometry, so nothing finer is asserted. Facilities are associated
with a local area only through a matching published city label in the same region.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

COUNTRY_ID, STATE_ID = "AE", "AE-AZ"
COUNTRY = ("United Arab Emirates", "الإمارات العربية المتحدة")
STATE = ("Abu Dhabi Emirate", "إمارة أبوظبي")

# Transliteration variants between synthetic local-area labels and published SDI city labels
# (same place, different romanization). Ambiguous pairs (e.g. Ruwais vs "AL RUWAYS INDUSTRIAL
# CITY") are deliberately not mapped: their facility coverage is reported as unknown.
LABEL_CROSSWALK = {
    "MUSSAFAH": "MUSAFFAH",
    "BANIYAS": "BANI YAS",
    "AL TOWAYYA": "AL TIWAYYA",
}


@dataclass(frozen=True)
class Area:
    area_id: str
    level: str
    parent_area_id: str | None
    name_en: str
    name_ar: str | None
    region_id: int | None
    source: str
    source_label: str | None
    verification_status: str


def normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z ]", "", label.upper())).strip()


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def district_id(region_code: str) -> str:
    return f"{STATE_ID}-{region_code}"


def local_area_id(region_code: str, label: str) -> str:
    return f"{district_id(region_code)}-L-{_slug(label)}"


def city_area_id(region_code: str, label: str) -> str:
    return f"{district_id(region_code)}-C-{_slug(normalize_label(label))}"


def facility_city_key(label: str | None) -> str | None:
    """Normalized published city label, or None when it is blank or names a whole region."""
    if not label or not label.strip():
        return None
    key = normalize_label(label)
    return None if not key or key.endswith(" REGION") else key


def local_to_city_key(local_label: str) -> tuple[str, str]:
    """(normalized facility city label, association basis) for a local-area label."""
    key = normalize_label(local_label)
    if key in LABEL_CROSSWALK:
        return LABEL_CROSSWALK[key], "transliteration_crosswalk"
    return key, "exact_label"


def build_hierarchy(
    regions: list[tuple[int, str, str, str | None]],
    local_labels: set[tuple[int, str]],
    city_labels: dict[tuple[int, str], str],
) -> dict[str, Area]:
    """All areas. `city_labels` maps (region_id, normalized key) -> display label."""
    code = {rid: c for rid, c, _, _ in regions}
    areas = [
        Area(COUNTRY_ID, "country", None, *COUNTRY, None, "iso_3166", None, "verified_reference"),
        Area(STATE_ID, "state", COUNTRY_ID, *STATE, None, "iso_3166", None, "verified_reference"),
    ]
    areas += [
        Area(district_id(c), "district", STATE_ID, en, ar, rid, "official_region", en, "verified_reference")
        for rid, c, en, ar in regions
    ]
    areas += [
        Area(local_area_id(code[rid], label), "local_area", district_id(code[rid]), label, None, rid,
             "synthetic_patient_label", label, "synthetic_label")
        for rid, label in sorted(local_labels) if rid in code
    ]
    areas += [
        Area(city_area_id(code[rid], key), "city", district_id(code[rid]), display, None, rid,
             "sdi_facility_city_label", display, "published_label")
        for (rid, key), display in sorted(city_labels.items()) if rid in code
    ]
    return {a.area_id: a for a in areas}
