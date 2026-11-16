"""Parsing, normalisation and validation for the `official` loader. No database access.

Specification: docs/mappings/official-source-to-table-mapping.md ("OFF") and
docs/mappings/data-loading-and-validation-strategy.md. Everything here works in memory on files that were
already checksum-verified; nothing is written, repaired or guessed. A violated assertion raises
`UnitError` (that unit is quarantined, others may proceed) or `FatalError` (nothing is written).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

LOADER_VERSION = "official-loader/1.0.0"
TRANSFORM_VERSION = "facility-geo-repair/1.0.0"  # re-implementation of build_facilities.py (OFF §9.1, OU-8)

UNLABELLED = "(unlabelled)"
DIMENSION_TYPES = (
    "region", "citizenship", "gender", "age_group", "cause_of_death",
    "disease_type", "measure_item", "insurance_type", "sector", "bed_type",
)
# source column prefix -> dimension_type (OFF §6). Any other `*_EN` column is a load error.
DIMENSION_COLUMNS = {
    "REGION": "region", "CITIZENSHIP": "citizenship", "GENDER": "gender", "AGE_GROUP": "age_group",
    "CAUSE_DEATH": "cause_of_death", "DISEASE_TYPE": "disease_type", "INDICATOR": "measure_item",
    "TYPE": "insurance_type", "SECTORS": "sector", "BED_TYPE": "bed_type",
}
NON_DIMENSION_EN = {"MONTH_EN", "QUARTER_EN"}  # always null in the API (verified)
PROJECTED_INDICATORS = frozenset({4866, 4868, 4869, 4870})
# The only duplicate natural keys the loader accepts, by 0-based row ordinal (OFF §8.3, D5).
KNOWN_DUPLICATE_ROWS = {3422: frozenset({104, 657})}
# Reviewed `unit_raw -> measure_kind` seed (OFF §5, OU-10). None has been reviewed, so every indicator is
# `unclassified` and nothing is additive. Add entries only from a signed review.
REVIEWED_MEASURE_KIND: dict[str, str] = {}
REGIONS = (  # region_id, code, scad_label, sdi_label — codes and ids are loader constants (OFF §4)
    (1, "AD", "Abu Dhabi Region", "Abu Dhabi"),
    (2, "AIN", "Al Ain Region", "Al Ain"),
    (3, "DHF", "Al Dhafra Region", "Al Dhafra"),
)
LON_MIN, LON_MAX = 51.0, 56.5
LAT_MIN, LAT_MAX = 22.0, 25.5
SDI_LAYERS = (
    "clinics", "diagnostic_centers", "dialysis_centre", "health_centres", "hospitals",
    "mobile_health_unit", "pharmacy", "provision_health_service", "rehabilitation_center",
)
# Files in raw_checksums.sha256 that map to no manifest source (OU-14): verified, reported, not registered.
KNOWN_UNMAPPED = frozenset({"data/raw/scad/scad_health_tables_en.xlsx"})
IGNORED_ON_DISK = frozenset({".gitkeep", ".DS_Store"})
# Missing-cell markers of the SCAD workbooks (D3: meaning unassigned). The API has none.
WORKBOOK_MARKERS = frozenset({"-", ":"})

# Expected counts, recomputed from the files (OFF §8, strategy §8). A legitimately changed input needs this
# table updated in the same reviewed change. `blocking` mismatches stop the run before any write.
EXPECTED = {
    "source": (24, True), "source_file": (214, True), "region": (3, True), "indicator": (86, True),
    "indicator_dimension": (87, True), "dimension_member": (195, False), "observation": (14913, True),
    "observation_leaf": (9912, True), "observation_aggregate": (5001, True), "observation_flagged": (2, True),
    "facility": (5339, True), "facility_identified": (4905, True), "facility_unidentified": (434, True),
    "license_status_map": (14, False),
}
EXPECTED_GEO = {"ok": 5299, "swapped_repaired": 31, "missing_placeholder": 6, "out_of_bounds": 3}


class LoaderError(Exception):
    """Base class; `kind` is the severity class of strategy §9.1."""
    kind = "UNIT-FAIL"


class FatalError(LoaderError):
    kind = "FATAL"


class UnitError(LoaderError):
    kind = "UNIT-FAIL"


# --------------------------------------------------------------------------------------------------
# Repository inputs and checksums (strategy §3-§4)
# --------------------------------------------------------------------------------------------------
def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_checksum_list(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    path = root / "data/reference/raw_checksums.sha256"
    if not path.is_file():
        raise FatalError(f"{path} not found")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        digest, _, rel = line.partition("  ")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not rel.startswith("data/raw/"):
            raise FatalError(f"malformed checksum line: {line!r}")
        if rel in out:
            raise FatalError(f"duplicate checksum entry for {rel}")
        out[rel] = digest
    return out


def verify_raw_files(root: Path) -> dict[str, dict]:
    """Every file on disk must be listed and match its hash; every listed file must exist. FATAL otherwise."""
    listed = read_checksum_list(root)
    on_disk = {
        p.relative_to(root).as_posix()
        for p in (root / "data/raw").rglob("*")
        if p.is_file() and p.name not in IGNORED_ON_DISK
    }
    if on_disk != set(listed):
        raise FatalError(
            f"raw file inventory differs from raw_checksums.sha256: on disk only {sorted(on_disk - set(listed))}, "
            f"listed only {sorted(set(listed) - on_disk)}")
    out = {}
    bad = []
    for rel, expected in sorted(listed.items()):
        data = (root / rel).read_bytes()
        actual = sha256_bytes(data)
        if actual != expected:
            bad.append(rel)
        out[rel] = {"sha256": actual, "byte_size": len(data)}
    if bad:
        raise FatalError(f"checksum mismatch (raw files are immutable): {bad}")
    return out


# --------------------------------------------------------------------------------------------------
# source (OFF §2) and source_file (OFF §1, §3)
# --------------------------------------------------------------------------------------------------
def load_manifest(root: Path) -> tuple[dict, str]:
    path = root / "data/reference/source_manifest.yaml"
    if not path.is_file():
        raise FatalError(f"{path} not found")
    raw = path.read_bytes()
    manifest = yaml.safe_load(raw)
    return manifest, sha256_bytes(raw)


def source_rows(manifest: dict) -> list[dict]:
    version = manifest.get("manifest_version")
    if not version:
        raise FatalError("manifest has no manifest_version")
    rows, seen = [], set()
    for s in manifest["sources"]:
        sid = s.get("id")
        if not sid or sid in seen:
            raise FatalError(f"manifest source id missing or duplicated: {sid!r}")
        seen.add(sid)
        for required in ("name", "publisher"):
            if not s.get(required):
                raise FatalError(f"{sid}: manifest field {required!r} is required")
        acq = s.get("acquisition") or {}
        state = acq.get("state")
        obtained = state in ("dataset_obtained", "document_obtained")
        validation = s.get("validation")
        if validation == "clinical":
            raise FatalError(f"{sid}: validation 'clinical' is rejected (nothing is clinically validated)")
        rows.append({
            "source_id": sid,
            "name": s["name"],
            "publisher": s["publisher"],
            "url": s.get("url") or s.get("landing_page") or s.get("service_url"),
            "licence_text": s.get("licence") or s.get("permitted_reuse"),
            "attribution_statement": None,  # no manifest field (OU-15)
            "acquisition_state": state,
            "validation_state": validation if obtained else None,
            "fit_for_use": None,
            "contains_data": None,
            "acquisition_reason": acq.get("reason") if state in ("blocked", "excluded") else None,
            "manifest_version": str(version),
        })
    by_id = {r["source_id"]: r for r in rows}
    for sid in ("SRC-02-IFHAS", "SRC-03-WCV"):
        if sid not in by_id or by_id[sid]["acquisition_state"] != "blocked":
            raise FatalError(f"{sid} must load as 'blocked' (the standard's text is not held)")
    return rows


@dataclass(frozen=True)
class FileClass:
    source_id: str
    file_role: str
    contains_data: bool
    fit_for_use: bool | None = None


def classify_file(rel: str) -> FileClass | None:
    """Ownership and role by path, never by content sniffing (OFF §1). None = unmapped (OU-14)."""
    name = rel.rsplit("/", 1)[-1]
    if rel.startswith("data/raw/statad_api/indicator_detail/") and name.endswith(".json"):
        return FileClass("SRC-17-SCAD-STATISTICS-API", "indicator_detail", True)
    if rel.startswith("data/raw/statad_api/indicator_metadata/") and name.endswith(".xlsx"):
        return FileClass("SRC-17-SCAD-STATISTICS-API", "indicator_metadata", True)
    if rel == "data/raw/statad_api/acquisition_log.json":
        return FileClass("SRC-17-SCAD-STATISTICS-API", "other", False)
    if rel.startswith("data/raw/abudhabi_sdi/") and name.endswith(".geojson"):
        return FileClass("SRC-18-ABUDHABI-SDI-FACILITIES", "facility_geojson", True)
    if rel == "data/raw/abudhabi_sdi/acquisition_log.json":
        return FileClass("SRC-18-ABUDHABI-SDI-FACILITIES", "other", False)
    scad = {
        "scad_health_statistics_2022_en.xlsx": "SRC-10-SCAD-HEALTH-2022",
        "scad_birth_statistics_2024_en.xlsx": "SRC-11-SCAD-BIRTHS-2024",
        "scad_birth_statistics_2025_en.xlsx": "SRC-19-SCAD-VITAL-2025",
        "scad_death_statistics_2025_en.xlsx": "SRC-19-SCAD-VITAL-2025",
    }
    if rel.startswith("data/raw/scad/") and name in scad:
        return FileClass(scad[name], "publication_workbook", True)
    if rel.startswith("data/raw/abudhabi_opendata/metadata/") and name.endswith(".json"):
        sid = "SRC-21-MOHAP-NURSES-2008" if name.startswith("mohap_") else "SRC-20-ABUDHABI-OPENDATA-CATALOGUE"
        return FileClass(sid, "catalogue", True)
    if rel == "data/raw/abudhabi_opendata/catalogue_search_results.json":
        return FileClass("SRC-20-ABUDHABI-OPENDATA-CATALOGUE", "catalogue", True)
    if rel == "data/raw/abudhabi_opendata/acquisition_log.json":
        return FileClass("SRC-20-ABUDHABI-OPENDATA-CATALOGUE", "other", False)
    if rel.startswith("data/raw/abudhabi_opendata/files/") and name.startswith("govdigital_") and name.endswith(".xlsx"):
        return FileClass("SRC-20-ABUDHABI-OPENDATA-CATALOGUE", "other", False)
    if rel.startswith("data/raw/abudhabi_opendata/files/") and name.startswith("mohap_nurses_") and name.endswith(".xlsx"):
        return FileClass("SRC-21-MOHAP-NURSES-2008", "other", True, fit_for_use=False)
    return None


def _workbook_cells(path: Path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                yield ws.title, row
    finally:
        wb.close()


def source_file_rows(root: Path, verified: dict[str, dict], manifest: dict) -> tuple[list[dict], list[str]]:
    """One row per mapped file (214) and the list of unmapped relative paths (known: OU-14)."""
    last_modified = {}
    for s in manifest["sources"]:
        acq = s.get("acquisition") or {}
        for f in acq.get("files") or []:
            if f.get("local_path") and f.get("last_modified_header"):
                last_modified[f["local_path"]] = f["last_modified_header"]
        if acq.get("local_path") and acq.get("last_modified_header"):
            last_modified[acq["local_path"]] = acq["last_modified_header"]

    rows, unmapped = [], []
    for rel, info in sorted(verified.items()):
        fc = classify_file(rel)
        if fc is None:
            if rel not in KNOWN_UNMAPPED:
                raise FatalError(f"unmapped_file: {rel} matches no ownership rule (never guessed)")
            unmapped.append(rel)
            continue
        path = root / rel
        retrieved_at, note = None, None  # NULL = not recorded; never defaulted to load time (CD-9)
        if fc.file_role == "facility_geojson":
            stamp = json.loads(path.read_bytes())["_source"]["retrieved"]
            retrieved_at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        elif fc.file_role == "indicator_detail":
            note = f"Metadata.updated={json.loads(path.read_bytes())['Data']['Metadata'].get('updated')}"
        elif fc.file_role == "indicator_metadata":
            note = f"Last data update={read_metadata_workbook(path).get('last_update_raw')}"
        elif fc.file_role == "publication_workbook":
            lm = last_modified.get(rel)
            note = f"HTTP Last-Modified: {lm}" if lm else None
        elif fc.file_role == "catalogue" and rel.startswith("data/raw/abudhabi_opendata/metadata/"):
            modified = json.loads(path.read_bytes()).get("modified")
            note = f"modified={modified}" if modified else None
        contains_data = fc.contains_data
        if rel.startswith("data/raw/abudhabi_opendata/files/govdigital_"):
            # Each holds one dead-URL cell, no data: re-assert (OFF §3).
            nonempty = sum(1 for _, r in _workbook_cells(path) for c in r if c not in (None, ""))
            if nonempty > 1:
                raise FatalError(f"{rel}: expected at most one non-empty cell, found {nonempty}")
        rows.append({
            "source_id": fc.source_id, "relative_path": rel, "sha256": info["sha256"],
            "byte_size": info["byte_size"], "file_role": fc.file_role, "retrieved_at": retrieved_at,
            "source_effective_note": note, "contains_data": contains_data, "fit_for_use": fc.fit_for_use,
            "loader_version": LOADER_VERSION,
        })
    return rows, unmapped


# --------------------------------------------------------------------------------------------------
# Value and marker normalisation (OFF §8.1)
# --------------------------------------------------------------------------------------------------
def normalize_value(raw: Any, markers: frozenset[str] = frozenset()) -> tuple[Decimal | None, str | None]:
    """Return (value, value_marker_raw), exactly one of which is not None (CHECK value_xor_marker).

    `markers` is the source-specific set of missing-cell markers. The API has none, so a null or an unknown
    string is an error; the workbooks use `-` / `:` (meaning unassigned, D3). A marker is preserved verbatim
    and never becomes 0; a source-stated `0` stays 0.
    """
    if isinstance(raw, bool) or raw is None:
        raise UnitError(f"missing VALUE {raw!r} with no source-defined marker; refusing to invent one")
    if isinstance(raw, str):
        if raw in markers:
            return None, raw
        raise UnitError(f"VALUE {raw!r} is neither a number nor a known missing marker")
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(raw) if not isinstance(raw, Decimal) else raw, None
    raise UnitError(f"VALUE of unsupported type {type(raw).__name__}")


# --------------------------------------------------------------------------------------------------
# dimension_member (OFF §7)
# --------------------------------------------------------------------------------------------------
_AGE_RANGE = re.compile(r"^(\d+)-(\d+)$")
_AGE_OPEN = re.compile(r"^(\d+)\+$")
_DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def member_role(dimension_type: str, label: str | None) -> str:
    if label is None:
        return "unlabelled"
    if label == "Total" or (dimension_type == "region" and label == "Emirate of Abu Dhabi"):
        return "aggregate"
    if label in ("Missing/Unknown", "Unknown"):
        return "missing_unknown"
    folded = label.casefold()
    if folded == "not stated":
        return "not_stated"
    if folded == "abroad":
        return "abroad"
    if folded in ("other", "others", "other diseases"):
        return "other"
    return "leaf"


def member_spec(dimension_type: str, en: str | None, ar: str | None) -> dict:
    """The dimension_member row for one distinct (type, English, Arabic) label triple."""
    if en == UNLABELLED:
        raise UnitError(f"a real label equals the reserved placeholder {UNLABELLED!r}")
    if en is not None and not isinstance(en, str):
        raise UnitError(f"{dimension_type}: label {en!r} is not a string (no coercion is applied)")
    raw_en = UNLABELLED if en is None else en
    spec = {
        "dimension_type": dimension_type, "raw_label_en": raw_en, "raw_label_ar": ar,
        "canonical_key": raw_en if en is None else " ".join(en.split()).casefold(),
        "member_role": member_role(dimension_type, en), "region_id": None, "scheme_code": None,
        "age_min_months": None, "age_max_months": None, "correction_state": "none",
        "label_corrected_en": None, "correction_basis": None,
    }
    if en is None:
        return spec
    if dimension_type == "region":
        for rid, _code, scad_label, _sdi in REGIONS:
            if en == scad_label:
                spec["region_id"] = rid
    if _DATE_LIKE.match(en):
        if dimension_type != "age_group":
            raise UnitError(f"{dimension_type}: date-like label {en!r} on a non-age dimension")
        spec["correction_state"] = "pending"  # D4: bounds stay NULL, member unusable as a band
        return spec
    if dimension_type == "age_group" and spec["member_role"] == "leaf":
        if (m := _AGE_RANGE.match(en)) and int(m[1]) <= int(m[2]):
            lo, hi = int(m[1]), int(m[2])
            spec.update(age_min_months=lo * 12, age_max_months=hi * 12 + 11,
                        scheme_code={5: "5y", 10: "10y", 15: "15y"}.get(hi - lo + 1, "custom"))
        elif m := _AGE_OPEN.match(en):
            spec.update(age_min_months=int(m[1]) * 12, age_max_months=None, scheme_code="open")
        elif en == "Less than one year":
            spec.update(age_min_months=0, age_max_months=11, scheme_code="infant")
    return spec


# --------------------------------------------------------------------------------------------------
# indicator metadata workbook (OFF §5)
# --------------------------------------------------------------------------------------------------
_META_KEYS = {
    "Statistical population": "statistical_population",
    "Geographic coverage": "geographic_coverage",
    "Statistical calculation method": "calculation_method",
    "Data sources": "data_sources_text",
    "Last data update": "last_update_raw",
    "Measurement unit": "measurement_unit",
}


def read_metadata_workbook(path: Path) -> dict:
    rows = [(t, r) for t, r in _workbook_cells(path)]
    if not rows or {t for t, _ in rows} != {"Meta data & Methodology"}:
        raise UnitError(f"{path.name}: expected exactly one sheet 'Meta data & Methodology'")
    if tuple(rows[0][1][:2]) != ("Title", "Value"):
        raise UnitError(f"{path.name}: unexpected header row {rows[0][1][:2]!r}")
    out: dict[str, Any] = {}
    for _, r in rows[1:]:
        if not r or r[0] is None:
            continue
        key = str(r[0]).replace("\xa0", " ").strip()  # 'Geographic coverage\xa0' has a trailing NBSP
        field_name = _META_KEYS.get(key)
        if field_name is None:
            continue
        value = r[1] if len(r) > 1 else None
        if value is None:
            out[field_name] = None
        elif field_name == "last_update_raw" and isinstance(value, (int, float)) and not isinstance(value, bool) \
                and float(value).is_integer():
            out[field_name] = str(int(value))  # a sentinel/identifier, never a date
        elif isinstance(value, str):
            out[field_name] = value
        else:
            raise UnitError(f"{path.name}: {key!r} holds a {type(value).__name__}; refusing to coerce it")
    return out


# --------------------------------------------------------------------------------------------------
# indicator + observations (OFF §5, §6, §8)
# --------------------------------------------------------------------------------------------------
@dataclass
class IndicatorUnit:
    indicator_id: int
    rel_path: str
    indicator: dict
    metadata_rel_path: str | None
    dimensions: list[dict]
    members: dict[tuple, dict]  # (type, en, ar) -> member row
    observations: list[dict]  # `members` is {dimension_type: (type, en, ar)}
    warnings: list[str] = field(default_factory=list)


def _json(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8"), parse_float=Decimal)


def parse_indicator_file(root: Path, rel: str, metadata_rels: dict[int, str]) -> IndicatorUnit:
    path = root / rel
    doc = _json(path)
    stem = path.stem
    prefix = re.match(r"^(\d+)_", stem)
    if not prefix:
        raise UnitError(f"{rel}: file name has no numeric indicator prefix")
    data = doc.get("Data") or {}
    cfg_list = data.get("Configuration") or []
    if len(cfg_list) != 1:
        raise UnitError(f"{rel}: expected exactly one Configuration entry, found {len(cfg_list)}")
    cfg, meta, rows = cfg_list[0], data.get("Metadata") or {}, data.get("Data")
    indicator_id = int(cfg["indicatorId"])
    if indicator_id != int(prefix[1]):
        raise UnitError(f"{rel}: indicatorId {indicator_id} differs from the file-name prefix {prefix[1]}")
    if not isinstance(rows, list) or not rows:
        raise UnitError(f"{rel}: no observation rows")
    if doc.get("TotalItems") != len(rows):
        raise UnitError(f"{rel}: TotalItems {doc.get('TotalItems')} != {len(rows)} rows")
    if cfg.get("timeUnit") != ["Yearly"]:
        raise UnitError(f"{rel}: timeUnit {cfg.get('timeUnit')!r} is not ['Yearly']")
    title = (meta.get("component_title") or "").strip()
    unit_raw = cfg.get("unit")
    if not title or not unit_raw:
        raise UnitError(f"{rel}: title and unit are required")
    projected = bool(re.search("(?i)projection", title))
    if projected != (indicator_id in PROJECTED_INDICATORS):
        raise UnitError(f"{rel}: projection title rule ({projected}) disagrees with the known projected set")

    # dimensions, in first-row key order; every row must carry the same keys
    keyset = {tuple(r.keys()) for r in rows}
    if len(keyset) != 1:
        raise UnitError(f"{rel}: rows do not all carry the same columns")
    dims: list[dict] = []
    for key in rows[0]:
        if not key.endswith("_EN") or key in NON_DIMENSION_EN:
            continue
        prefix_name = key[: -len("_EN")]
        if prefix_name not in DIMENSION_COLUMNS:
            raise UnitError(f"{rel}: unknown dimension column {key!r} (a new dimension is a design change)")
        dims.append({"indicator_id": indicator_id, "dimension_type": DIMENSION_COLUMNS[prefix_name],
                     "source_column": key, "ordinal": len(dims) + 1})
    segments = [s for s in (data.get("Properties") or "").split("|") if s]
    if len(segments) != len(dims):
        raise UnitError(f"{rel}: Properties lists {len(segments)} dimensions but rows carry {len(dims)}")
    if len(dims) > 3:
        raise UnitError(f"{rel}: more than three dimensions")

    indicator = {
        "indicator_id": indicator_id, "slug": stem, "title_en": title,
        "definition_en": (meta.get("component_subtitle") or None),
        "unit_raw": unit_raw, "measure_kind": REVIEWED_MEASURE_KIND.get(unit_raw, "unclassified"),
        "series_kind": "projected" if projected else "observed", "periodicity": "annual",
        "region_basis": ("facility_location" if "Facility Region" in title
                         else "residence" if "Region of Residence" in title else "unspecified"),
        "statistical_population": None, "geographic_coverage": None, "calculation_method": None,
        "data_sources_text": None, "last_update_raw": None,
    }
    warnings: list[str] = []
    meta_rel = metadata_rels.get(indicator_id)
    if meta_rel:
        md = read_metadata_workbook(root / meta_rel)
        for k in ("statistical_population", "geographic_coverage", "calculation_method", "data_sources_text",
                  "last_update_raw"):
            indicator[k] = md.get(k)
        if md.get("measurement_unit") != unit_raw:
            warnings.append(f"{indicator_id}: workbook unit {md.get('measurement_unit')!r} != API unit {unit_raw!r}")

    members: dict[tuple, dict] = {}
    observations: list[dict] = []
    identity: dict[tuple, list[int]] = {}
    for ordinal, r in enumerate(rows):
        year, obs_dt = r.get("YEAR"), r.get("OBS_DT")
        if not (isinstance(year, str) and year.isdigit() and isinstance(obs_dt, str) and obs_dt[:4] == year):
            raise UnitError(f"{rel}[{ordinal}]: YEAR {year!r} does not match OBS_DT {obs_dt!r}")
        value, marker = normalize_value(r.get("VALUE"))  # the API has no markers
        row_members: dict[str, tuple] = {}
        aggregate = False
        for d in dims:
            col = d["source_column"][: -len("_EN")]
            en, ar = r[f"{col}_EN"], r.get(f"{col}_AR")
            key = (d["dimension_type"], UNLABELLED if en is None else en, ar)
            if key not in members:
                members[key] = member_spec(d["dimension_type"], en, ar)
            row_members[d["dimension_type"]] = key
            aggregate = aggregate or members[key]["member_role"] == "aggregate"
        identity.setdefault((int(year), tuple(row_members.get(t) for t in DIMENSION_TYPES)), []).append(ordinal)
        observations.append({
            "indicator_id": indicator_id, "period_year": int(year), "period_type": "year", "obs_date_raw": obs_dt,
            "members": row_members, "value": value, "value_marker_raw": marker,
            "row_role": "aggregate" if aggregate else "leaf", "source_row_ordinal": ordinal, "quality_flag": None,
        })
    flagged = {o for ords in identity.values() if len(ords) > 1 for o in ords}
    if flagged != set(KNOWN_DUPLICATE_ROWS.get(indicator_id, ())):
        raise UnitError(f"{rel}: unexpected duplicate natural-key rows {sorted(flagged)}; a decision is needed")
    for o in observations:
        if o["source_row_ordinal"] in flagged:
            o["quality_flag"] = "duplicate_key_conflict"
    return IndicatorUnit(indicator_id, rel, indicator, meta_rel, dims, members, observations, warnings)


def metadata_rel_paths(verified: dict[str, dict]) -> dict[int, str]:
    out: dict[int, str] = {}
    for rel in verified:
        if rel.startswith("data/raw/statad_api/indicator_metadata/") and rel.endswith("_metadata.xlsx"):
            i = int(rel.rsplit("/", 1)[1].split("_", 1)[0])
            if i in out:
                raise FatalError(f"two metadata workbooks for indicator {i}")
            out[i] = rel
    return out


def region_rows(units: list[IndicatorUnit]) -> list[dict]:
    """The three regions, with SCAD labels asserted to exist in the data (OFF §4)."""
    scad_ar: dict[str, set] = {}
    for u in units:
        for (dt_, en, ar) in u.members:
            if dt_ == "region":
                scad_ar.setdefault(en, set()).add(ar)
    out = []
    for rid, code, scad_label, sdi_label in REGIONS:
        if scad_label not in scad_ar:
            raise FatalError(f"region label {scad_label!r} not found in the SCAD data")
        ars = scad_ar[scad_label]
        out.append({"region_id": rid, "region_code": code, "name_en": scad_label,
                    "name_ar": next(iter(ars)) if len(ars) == 1 and None not in ars else None,
                    "scad_label": scad_label, "sdi_label": sdi_label})
    return out


# --------------------------------------------------------------------------------------------------
# facilities (OFF §9, §10)
# --------------------------------------------------------------------------------------------------
def _in_box(lon, lat) -> bool:
    return lon is not None and lat is not None and LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX


def classify_coordinates(lon, lat) -> tuple[str, float | None, float | None]:
    """(geo_quality, usable longitude, usable latitude): the procedure of build_facilities.py (OFF §9.1).

    `ok` means "inside the rectangle" and nothing more (CD-11). Out-of-bounds values are never repaired.
    """
    if lon is None or lat is None:
        raise UnitError("null geometry has no geo_quality value in the approved design (D-6)")
    if lon == 0 and lat == 0:
        return "missing_placeholder", None, None
    if _in_box(lon, lat):
        return "ok", lon, lat
    if _in_box(lat, lon):
        return "swapped_repaired", lat, lon
    return "out_of_bounds", None, None


def parse_bed_capacity(raw, identified: bool) -> int | None:
    """Three source states, one canonical column (CD-8; the raw GeoJSON keeps the distinction).

    "0" -> 0 (source-stated zero) · "<n>" -> n · "" -> NULL (not recorded, never 0) · null -> NULL
    (only on unidentified records; asserted so that the NULL is always explainable from `identity_status`).
    """
    if raw is None:
        if identified:
            raise UnitError("INPATIENTBEDCAPACITY is null on an identified facility")
        return None
    if not isinstance(raw, str):
        raise UnitError(f"INPATIENTBEDCAPACITY {raw!r} is not a string")
    if raw == "":
        if not identified:
            raise UnitError("INPATIENTBEDCAPACITY is '' on an unidentified record")
        return None
    if not raw.isascii() or not raw.isdigit():
        raise UnitError(f"INPATIENTBEDCAPACITY {raw!r} is not a digit string")
    return int(raw)


def _yes_no(raw, field_name: str, extra: dict | None = None) -> bool | None:
    if raw is None:
        return None
    table = {"Yes": True, "No": False, **(extra or {})}
    if raw not in table:
        raise UnitError(f"{field_name}: unexpected value {raw!r}")
    return table[raw]


def _empty_to_none(raw):
    return None if raw in (None, "") else raw


@dataclass
class FacilityUnit:
    rows: list[dict]
    license_statuses: list[str]
    layer_counts: dict[str, int]
    geo_counts: dict[str, int]
    region_labels: set[str]


def parse_facilities(root: Path, sdi_to_region_id: dict[str, int], file_rels: dict[str, str]) -> FacilityUnit:
    """`file_rels` maps source_layer -> repository-relative path (the registered source_file)."""
    log = json.loads((root / "data/raw/abudhabi_sdi/acquisition_log.json").read_bytes())
    logged = {v["slug"]: v["feature_count"] for v in log.values()}
    rows: list[dict] = []
    statuses: set[str] = set()
    region_labels: set[str] = set()
    layer_counts: dict[str, int] = {}
    geo_counts = {k: 0 for k in EXPECTED_GEO}
    for layer in SDI_LAYERS:
        doc = json.loads((root / file_rels[layer]).read_bytes())
        feats = doc["features"]
        if logged.get(layer) != len(feats):
            raise UnitError(f"{layer}: {len(feats)} features but the acquisition log records {logged.get(layer)}")
        layer_counts[layer] = len(feats)
        for ft in feats:
            p, g = ft.get("properties") or {}, ft.get("geometry") or {}
            ref = f"{layer}/OBJECTID {p.get('OBJECTID')}"
            try:
                if g.get("type") != "Point" or len(g.get("coordinates") or []) < 2:
                    raise UnitError("geometry is not a Point with coordinates")
                lon_s, lat_s = float(g["coordinates"][0]), float(g["coordinates"][1])
                quality, lon, lat = classify_coordinates(lon_s, lat_s)
                lic, name = p.get("FACILITYLICENSE"), p.get("FACILITYNAME")
                if (lic is None) != (name is None):
                    raise UnitError("exactly one of FACILITYLICENSE / FACILITYNAME is null")
                if lic is not None and (not isinstance(lic, str) or not lic.strip()):
                    raise UnitError("FACILITYLICENSE is blank")
                identified = lic is not None
                if not identified and layer != "rehabilitation_center":
                    raise UnitError("unidentified record outside rehabilitation_center")
                ch_fid = p.get("CH_FID")
                if not isinstance(ch_fid, str) or not ch_fid:
                    raise UnitError("CH_FID missing")
                region = p.get("REGION")
                if region is not None and region not in sdi_to_region_id:
                    raise UnitError(f"unknown REGION {region!r}")
                if region is not None:
                    region_labels.add(region)
                status = p.get("LICENSESTATUS")
                if status is not None:
                    statuses.add(status)
                rows.append({
                    "source_layer": layer, "source_object_id": int(p["OBJECTID"]), "ch_fid": ch_fid,
                    "license_no": lic, "identity_status": "identified" if identified else "unidentified",
                    "facility_name_en": name, "facility_name_ar": p.get("FACILITYNAMEAR"),
                    "type": p.get("TYPE"), "category": p.get("CATEGORY"), "subtype": p.get("SUBTYPE"),
                    "region_id": sdi_to_region_id.get(region), "city": p.get("CITY"),
                    "license_status_raw": status, "is_public_raw": p.get("ISPUBLIC"),
                    "is_public": _yes_no(p.get("ISPUBLIC"), "ISPUBLIC", {"N": False}),
                    "has_insurance": _yes_no(_empty_to_none(p.get("HASINSURANCE")), "HASINSURANCE"),
                    "inpatient_bed_capacity": parse_bed_capacity(p.get("INPATIENTBEDCAPACITY"), identified),
                    "beds_raw": _empty_to_none(p.get("BEDS")),
                    "specialities_raw": _empty_to_none(p.get("SPECIALITIES")),
                    "professionals_raw": _empty_to_none(p.get("PROFESSIONALS")),
                    "emergency_department": _yes_no(p.get("EMERGENCYDEPARTMENT"), "EMERGENCYDEPARTMENT"),
                    "pediatric_emergency_department": _yes_no(
                        p.get("PEDIATRICEMERGENCYDEPARTMENT"), "PEDIATRICEMERGENCYDEPARTMENT"),
                    "maternity_emergency_care": _yes_no(p.get("MATERNITYEMERGENCYCARE"), "MATERNITYEMERGENCYCARE"),
                    "home_care_services": _yes_no(p.get("HOMECARESERVICES"), "HOMECARESERVICES"),
                    "source_longitude": lon_s, "source_latitude": lat_s,  # exactly as published
                    "longitude": lon, "latitude": lat, "geo_quality": quality,
                    "source_effective_date": None,
                })
                geo_counts[quality] += 1
            except UnitError as exc:
                raise UnitError(f"{ref}: {exc}") from None
    keys = [(r["source_layer"], r["source_object_id"]) for r in rows]
    if len(set(keys)) != len(keys):
        raise UnitError("duplicate (source_layer, OBJECTID)")
    for col in ("ch_fid", "license_no"):
        vals = [r[col] for r in rows if r[col] is not None]
        if len(set(vals)) != len(vals):
            raise UnitError(f"{col} is not unique")
    return FacilityUnit(rows, sorted(statuses), layer_counts, geo_counts, region_labels)
