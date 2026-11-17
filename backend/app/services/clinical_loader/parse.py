"""Parse, validate, and project the clinical YAML rule bundle into database-ready rows.

Implements all validation and projection rules from `docs/mappings/clinical-yaml-to-database-mapping.md`:
- Strict Boolean validation (`isinstance(v, bool)`) across all Boolean fields
- NFKD slug generation (`slugify_component`) with collision rejection
- Partial-date triple parsing (`YYYY-MM-DD`, `YYYY-MM` with `from=None`, `None` -> `unknown`)
- Canonical `content_sha256` over the whole rule mapping
- Typed projections for all 54 rules and 10 rule types
- Parent-aware item effective authority recomputation (`effective_authority = status_is_verified AND parent_rule.is_authoritative`)
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

LOADER_VERSION = "0.1.0"

RULE_FILES = (
    ("ifhas", "ifhas/ifhas_rules.yaml"),
    ("well_child", "well_child/well_child_rules.yaml"),
)
SOURCES_FILE = "common/sources.yaml"
STATUS_FILE = "common/status_definitions.yaml"
QUESTIONS_FILE = "common/open_questions.yaml"
ALL_YAML_FILES = (
    SOURCES_FILE,
    STATUS_FILE,
    QUESTIONS_FILE,
    "ifhas/ifhas_rules.yaml",
    "well_child/well_child_rules.yaml",
)

ALLOWED_VERIFICATION_STATUSES = ("verified", "reported", "unresolved")
EVALUATION_STATUSES = (
    "eligible",
    "not_eligible",
    "due",
    "upcoming",
    "overdue",
    "completed",
    "unknown",
    "insufficient_information",
    "requires_clinical_review",
)
ITEM_LIST_KEYS = (
    "preventive_assessments",
    "developmental_assessments",
    "follow_up_requirements",
)
REQUIRED_RULE_METADATA = (
    "rule_id",
    "pathway",
    "rule_version",
    "source_name",
    "source_version",
    "source_reference",
    "verification_status",
    "effective_date",
    "last_reviewed",
    "description",
    "requires_clinical_review",
)
OPTIONAL_RULE_KEYS = (
    "rule_type",
    "effective_date_note",
    "open_question_ids",
    "history",
    "notes",
    "spec",
)
PROJECTION_COLUMNS = (
    "package_name",
    "package_group",
    "age_min_years",
    "age_max_years",
    "age_as_printed",
    "sexes",
    "frequency_type",
    "interval_value",
    "interval_unit",
    "visit_number",
    "visit_id",
    "recommended_age_months",
    "age_band",
    "instrument",
    "score_min",
    "score_max",
    "timing_value",
    "timing_unit",
    "timing_reference_event",
    "gate_attribute",
)

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YEAR_MONTH = re.compile(r"^\d{4}-\d{2}$")
_YEAR = re.compile(r"^\d{4}$")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class FatalError(RuntimeError):
    """Raised when clinical YAML or database state violates a mandatory loader invariant."""


def repo_root() -> Path:
    env_root = os.getenv("PULSE_REACH_REPO_ROOT")
    if env_root:
        return Path(env_root).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data-pipeline" / "rules").exists() or (
            parent / "data" / "reference" / "source_manifest.yaml"
        ).exists():
            return parent
    return here.parents[min(4, len(here.parents) - 1)]


def default_rules_dir() -> Path:
    from app.core.config import settings

    if settings.rules_dir:
        return Path(settings.rules_dir).resolve()
    return repo_root() / "data-pipeline" / "rules"


def default_manifest_path() -> Path:
    from app.core.config import settings

    if settings.data_dir:
        return Path(settings.data_dir).resolve() / "reference" / "source_manifest.yaml"
    return repo_root() / "data" / "reference" / "source_manifest.yaml"


def slugify_component(text: str) -> str:
    """NFKD-normalise -> drop combining marks -> lower-case -> replace non-[a-z0-9] runs with `_` -> strip `_`."""
    if not isinstance(text, str) or not text.strip():
        raise FatalError(f"component text must be a non-empty string, got {text!r}")
    norm = unicodedata.normalize("NFKD", text)
    without_combining = "".join(ch for ch in norm if not unicodedata.combining(ch))
    lowered = without_combining.lower()
    slug = _NON_ALNUM.sub("_", lowered).strip("_")
    if not slug:
        raise FatalError(f"component text {text!r} produced an empty slug")
    return slug


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()[:10]
    s = str(value).strip()
    return s or None


def _strict_bool(value: Any, field_name: str, where: str) -> bool:
    if isinstance(value, bool):
        return value
    raise FatalError(f"{where}: '{field_name}' must be a boolean (true or false), got {value!r}")


def parse_partial_date(
    value: Any, *, field_name: str, where: str
) -> tuple[str | None, str, _dt.date | None]:
    """Return `(text, precision, from_date)` per §3.1 of the mapping. Never invents first-of-month."""
    txt = _text(value)
    if txt is None:
        return (None, "unknown", None)
    if _DATE.match(txt):
        try:
            d = _dt.date.fromisoformat(txt)
        except ValueError as exc:
            raise FatalError(f"{where}: invalid calendar date in {field_name}: {txt!r}") from exc
        return (txt, "day", d)
    if _YEAR_MONTH.match(txt):
        month = int(txt[5:7])
        if not (1 <= month <= 12):
            raise FatalError(f"{where}: invalid month in {field_name}: {txt!r}")
        return (txt, "month", None)
    if _YEAR.match(txt):
        return (txt, "year", None)
    raise FatalError(
        f"{where}: {field_name} {value!r} must be YYYY-MM-DD, YYYY-MM, YYYY, or null"
    )


def _normalize_for_json(obj: Any) -> Any:
    if isinstance(obj, (_dt.date, _dt.datetime)):
        return obj.isoformat()[:10]
    if isinstance(obj, dict):
        return {str(k): _normalize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize_for_json(v) for v in obj]
    return obj


def compute_content_sha256(raw_rule: dict[str, Any]) -> str:
    """Canonical SHA-256 of the whole rule mapping (§3.3)."""
    norm = _normalize_for_json(raw_rule)
    payload = json.dumps(norm, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_semver(version: str, where: str = "rule") -> tuple[int, int, int]:
    if not isinstance(version, str) or not _SEMVER.match(version):
        raise FatalError(f"{where}: rule_version {version!r} must match X.Y.Z")
    parts = version.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def git_commit_if_clean(root: Path) -> str | None:
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if status.returncode != 0 or status.stdout.strip():
            return None
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return rev.stdout.strip() if rev.returncode == 0 else None
    except Exception:
        return None


def extract_rule_projections(
    raw_rule: dict[str, Any],
    where: str,
    *,
    wcv_due_window_authoritative: bool = False,
) -> dict[str, Any]:
    """Extract and validate the 20 typed projection columns for `clinical.rule` (§2.8.1)."""
    proj: dict[str, Any] = {col: None for col in PROJECTION_COLUMNS}
    rule_type = _text(raw_rule.get("rule_type"))
    spec = raw_rule.get("spec") or {}

    if rule_type == "screening_package":
        proj["package_name"] = _text(spec.get("package_name"))
        proj["package_group"] = _text(spec.get("package_group"))
        elig = spec.get("eligibility") or {}
        age = elig.get("age")
        if not isinstance(age, dict) or "min_years" not in age or "max_years" not in age or not _text(age.get("as_printed")):
            raise FatalError(f"{where}: screening_package requires spec.eligibility.age with min_years, max_years, as_printed")
        proj["age_min_years"] = int(age["min_years"]) if age["min_years"] is not None else None
        proj["age_max_years"] = int(age["max_years"]) if age["max_years"] is not None else None
        proj["age_as_printed"] = _text(age.get("as_printed"))
        sex = elig.get("sex")
        if not isinstance(sex, list) or not sex or not set(sex) <= {"female", "male"}:
            raise FatalError(f"{where}: screening_package requires spec.eligibility.sex subset of female/male")
        proj["sexes"] = list(sex)

        freq = spec.get("frequency")
        if not isinstance(freq, dict) or freq.get("type") not in ("recurring", "once_per_lifetime") or not _text(freq.get("as_printed")):
            raise FatalError(f"{where}: screening_package requires valid spec.frequency")
        ftype = freq["type"]
        proj["frequency_type"] = ftype
        interval = freq.get("interval")
        if ftype == "recurring":
            if not isinstance(interval, dict) or interval.get("value") is None or not _text(interval.get("unit")):
                raise FatalError(f"{where}: recurring screening_package requires interval.value and interval.unit")
            proj["interval_value"] = int(interval["value"])
            proj["interval_unit"] = _text(interval["unit"])
        else:
            if interval is not None:
                raise FatalError(f"{where}: once_per_lifetime package must have interval: null")
            proj["interval_value"] = None
            proj["interval_unit"] = None

        if "one_time" not in spec:
            raise FatalError(f"{where}: screening_package requires spec.one_time boolean")
        one_time = _strict_bool(spec["one_time"], "spec.one_time", where)
        if one_time != (ftype == "once_per_lifetime"):
            raise FatalError(
                f"{where}: spec.one_time={one_time} contradicts frequency.type={ftype!r}"
            )

    elif rule_type == "visit_schedule":
        if "visit_number" not in spec or "visit_id" not in spec:
            raise FatalError(f"{where}: visit_schedule requires visit_number and visit_id")
        proj["visit_number"] = int(spec["visit_number"])
        proj["visit_id"] = _text(spec["visit_id"])
        timing = spec.get("timing") or {}
        rec_age = timing.get("recommended_age") or {}
        if rec_age.get("unit") != "months" or rec_age.get("value") is None:
            raise FatalError(
                f"{where}: visit_schedule recommended_age.unit must be 'months' with integer value"
            )
        proj["recommended_age_months"] = int(rec_age["value"])
        proj["age_band"] = _text(timing.get("age_band"))
        if timing.get("due_window") is not None and not wcv_due_window_authoritative:
            raise FatalError(
                f"{where}: Well-Child visit due_window must be null while WCV-TIMING-DUE-WINDOW is not authoritative"
            )

    elif rule_type == "developmental_screening_tier":
        proj["instrument"] = _text(spec.get("instrument"))
        if not proj["instrument"]:
            raise FatalError(f"{where}: developmental_screening_tier requires spec.instrument")
        is_diag = _strict_bool(spec.get("is_diagnosis"), "spec.is_diagnosis", where)
        is_scr = _strict_bool(
            spec.get("is_screening_result_only"), "spec.is_screening_result_only", where
        )
        if is_diag is not False or is_scr is not True:
            raise FatalError(
                f"{where}: developmental_screening_tier must have is_diagnosis=false and is_screening_result_only=true"
            )
        score = spec.get("score")
        if score is not None:
            if not isinstance(score, dict):
                raise FatalError(f"{where}: spec.score must be a mapping")
            smin = score.get("min")
            smax = score.get("max")
            if smin is None and smax is not None:
                raise FatalError(f"{where}: score_min is None but score_max is {smax!r} (CU-9)")
            proj["score_min"] = Decimal(str(smin)) if smin is not None else None
            proj["score_max"] = Decimal(str(smax)) if smax is not None else None

    elif rule_type in ("workflow_timing", "follow_up_window"):
        timing = spec.get("timing")
        if isinstance(timing, dict) and "value" in timing and timing["value"] is not None:
            proj["timing_value"] = int(timing["value"])
            proj["timing_unit"] = _text(timing.get("unit"))
            proj["timing_reference_event"] = _text(timing.get("reference_event"))
        # Note: if timing has min_value/max_value (range, e.g. WCV-FU-SPECIALIST-EVALUATION-2-4W)
        # or no timing (IFHAS-WF-INVITATION-SYSTEM), all three timing projections remain None (CU-8).

    elif rule_type == "programme_eligibility":
        proj["gate_attribute"] = _text(spec.get("attribute"))

    return proj


@dataclass(frozen=True)
class ParsedClinicalBundle:
    loader_version: str
    bundle_sha256: str
    file_hashes: dict[str, str]
    config_versions: dict[str, str]
    git_commit: str | None
    clinical_review_status: str
    standards: list[dict[str, Any]]
    verification_statuses: list[dict[str, Any]]
    evaluation_statuses: list[dict[str, Any]]
    reason_codes: list[dict[str, Any]]
    guards: list[dict[str, Any]]
    open_questions: list[dict[str, Any]]
    rules: list[dict[str, Any]]
    conditions: list[dict[str, Any]]
    items: list[dict[str, Any]]
    rule_open_questions: list[dict[str, Any]]
    rule_item_open_questions: list[dict[str, Any]]
    derived_pathway_links: list[dict[str, str]] = field(default_factory=list)
    uncited_in_scope_rules: dict[str, list[str]] = field(default_factory=dict)


def parse_clinical_bundle(
    rules_dir: Path | None = None,
    manifest_path: Path | None = None,
) -> ParsedClinicalBundle:
    """Parse and validate the 5 YAML clinical rule files and cross-check the manifest."""
    base = Path(rules_dir) if rules_dir is not None else default_rules_dir()
    mpath = Path(manifest_path) if manifest_path is not None else default_manifest_path()

    # Step 1: Compute file hashes and bundle_sha256 sorted by relative path (§2.2)
    file_hashes: dict[str, str] = {}
    for rel in sorted(ALL_YAML_FILES):
        fpath = base / rel
        if not fpath.is_file():
            raise FatalError(f"missing clinical YAML file: {rel}")
        file_hashes[rel] = hashlib.sha256(fpath.read_bytes()).hexdigest()

    bundle_lines = "".join(f"{rel}\t{file_hashes[rel]}\n" for rel in sorted(file_hashes))
    bundle_sha256 = hashlib.sha256(bundle_lines.encode("utf-8")).hexdigest()

    # Step 2: Load manifest for standard cross-reference (§2.1)
    manifest_by_doc_ref: dict[str, dict[str, Any]] = {}
    if mpath.is_file():
        mdoc = yaml.safe_load(mpath.read_text(encoding="utf-8")) or {}
        for entry in mdoc.get("sources") or []:
            if isinstance(entry, dict) and entry.get("document_reference"):
                manifest_by_doc_ref[str(entry["document_reference"]).strip()] = entry

    # Step 3: Parse sources.yaml -> clinical.standard
    src_doc = yaml.safe_load((base / SOURCES_FILE).read_text(encoding="utf-8"))
    if not isinstance(src_doc, dict) or not isinstance(src_doc.get("sources"), list):
        raise FatalError(f"{SOURCES_FILE}: expected top-level 'sources' list")

    standards: list[dict[str, Any]] = []
    std_keys: set[tuple[str, str]] = set()
    for idx, s in enumerate(src_doc["sources"], 1):
        where = f"{SOURCES_FILE}[{idx}]"
        if not isinstance(s, dict):
            raise FatalError(f"{where}: standard entry must be a mapping")
        sname = _text(s.get("source_name"))
        sver = _text(s.get("source_version"))
        dref = _text(s.get("document_ref"))
        pub = _text(s.get("publisher"))
        if not (sname and sver and dref and pub):
            raise FatalError(f"{where}: missing required standard metadata")
        pub_t, pub_p, pub_f = parse_partial_date(
            s.get("publication_date"), field_name="publication_date", where=where
        )
        eff_t, eff_p, eff_f = parse_partial_date(
            s.get("effective_date"), field_name="effective_date", where=where
        )
        eff_note = _text(s.get("effective_date_note"))
        if eff_p == "unknown" and not eff_note:
            raise FatalError(f"{where}: effective_date is unknown/null without effective_date_note")

        m_entry = manifest_by_doc_ref.get(dref)
        manifest_source_id = _text(m_entry.get("id")) if m_entry else None
        acq_state = (
            _text((m_entry.get("acquisition") or {}).get("state"))
            if m_entry
            else "blocked"
        )
        if acq_state not in ("blocked", "document_obtained"):
            raise FatalError(
                f"{where}: manifest acquisition.state {acq_state!r} not in ('blocked', 'document_obtained')"
            )

        standards.append(
            {
                "source_name": sname,
                "source_version": sver,
                "document_ref": dref,
                "publisher": pub,
                "publication_date_text": pub_t,
                "publication_date_precision": pub_p,
                "publication_date_from": pub_f,
                "effective_date_text": eff_t,
                "effective_date_precision": eff_p,
                "effective_date_from": eff_f,
                "effective_date_note": eff_note,
                "revision_date_text": _text(s.get("revision_date")),
                "pdf_pages": int(s["pdf_pages"]) if s.get("pdf_pages") is not None else None,
                "url": _text(s.get("url")),
                "contact": _text(s.get("contact")),
                "status_note": _text(s.get("status_note")),
                "manifest_source_id": manifest_source_id,
                "acquisition_state": acq_state,
                "local_copy_sha256": None,
            }
        )
        std_keys.add((sname, sver))

    # Step 4: Parse status_definitions.yaml -> verification_status, evaluation_status, reason_code, guard
    st_doc = yaml.safe_load((base / STATUS_FILE).read_text(encoding="utf-8"))
    if not isinstance(st_doc, dict):
        raise FatalError(f"{STATUS_FILE}: top level must be a mapping")
    st_cfg_ver = _text(st_doc.get("config_version"))
    if not st_cfg_ver:
        raise FatalError(f"{STATUS_FILE}: missing config_version")

    verification_statuses: list[dict[str, Any]] = []
    for s in st_doc.get("verification_statuses") or []:
        if not isinstance(s, dict):
            raise FatalError(f"{STATUS_FILE}: verification_status entry must be a mapping")
        code = _text(s.get("id"))
        defn = _text(s.get("definition"))
        if not code or not defn:
            raise FatalError(f"{STATUS_FILE}: verification_status missing id or definition")
        if "may_drive_decisions" not in s:
            raise FatalError(f"{STATUS_FILE}: verification_status '{code}' missing may_drive_decisions")
        mdd = _strict_bool(
            s["may_drive_decisions"],
            "may_drive_decisions",
            f"{STATUS_FILE}: verification_status '{code}'",
        )
        if mdd != (code == "verified"):
            raise FatalError(
                f"{STATUS_FILE}: verification_status '{code}' has may_drive_decisions={mdd}"
            )
        verification_statuses.append(
            {"code": code, "definition": defn, "may_drive_decisions": mdd}
        )
    if {v["code"] for v in verification_statuses} != set(ALLOWED_VERIFICATION_STATUSES):
        raise FatalError(
            f"{STATUS_FILE}: verification_statuses must be {ALLOWED_VERIFICATION_STATUSES}"
        )

    evaluation_statuses: list[dict[str, Any]] = []
    for idx, s in enumerate(st_doc.get("evaluation_statuses") or [], 1):
        if not isinstance(s, dict):
            raise FatalError(f"{STATUS_FILE}: evaluation_status entry must be a mapping")
        code = _text(s.get("id"))
        defn = _text(s.get("definition"))
        if not code or not defn:
            raise FatalError(f"{STATUS_FILE}: evaluation_status missing id or definition")
        nif = s.get("never_inferred_from")
        if nif is not None and (not isinstance(nif, list) or not all(isinstance(x, str) for x in nif)):
            raise FatalError(f"{STATUS_FILE}: evaluation_status '{code}' never_inferred_from must be a list of strings")
        evaluation_statuses.append(
            {
                "code": code,
                "definition": defn,
                "requires_text": _text(s.get("requires")),
                "never_inferred_from": list(nif) if nif is not None else None,
                "sort_order": idx,
            }
        )
    eval_codes = {e["code"] for e in evaluation_statuses}
    if eval_codes != set(EVALUATION_STATUSES) or len(evaluation_statuses) != len(EVALUATION_STATUSES):
        raise FatalError(f"{STATUS_FILE}: evaluation_statuses must match {EVALUATION_STATUSES}")

    reason_codes: list[dict[str, Any]] = []
    rc_set: set[str] = set()
    for rc in st_doc.get("reason_codes") or []:
        code = _text(rc)
        if not code or code in rc_set:
            raise FatalError(f"{STATUS_FILE}: invalid or duplicate reason_code {rc!r}")
        rc_set.add(code)
        reason_codes.append({"code": code, "description": None})

    guards: list[dict[str, Any]] = []
    for g in st_doc.get("guards") or []:
        if not isinstance(g, dict):
            raise FatalError(f"{STATUS_FILE}: guard entry must be a mapping")
        gid = _text(g.get("id"))
        wtxt = _text(g.get("when"))
        res = _text(g.get("result"))
        rc = _text(g.get("reason_code"))
        if not (gid and wtxt and res and rc):
            raise FatalError(f"{STATUS_FILE}: guard {gid!r} missing required fields")
        if res not in eval_codes:
            raise FatalError(f"{STATUS_FILE}: guard '{gid}' references unknown evaluation_status '{res}'")
        if rc not in rc_set:
            raise FatalError(f"{STATUS_FILE}: guard '{gid}' references unknown reason_code '{rc}'")
        guards.append(
            {
                "guard_id": gid,
                "when_text": wtxt,
                "result_status": res,
                "reason_code": rc,
                "note": _text(g.get("note")),
            }
        )

    # Step 5: Parse open_questions.yaml -> open_question
    oq_doc = yaml.safe_load((base / QUESTIONS_FILE).read_text(encoding="utf-8"))
    if not isinstance(oq_doc, dict):
        raise FatalError(f"{QUESTIONS_FILE}: top level must be a mapping")
    oq_cfg_ver = _text(oq_doc.get("config_version"))
    if not oq_cfg_ver:
        raise FatalError(f"{QUESTIONS_FILE}: missing config_version")

    open_questions: list[dict[str, Any]] = []
    oq_ids: set[str] = set()
    for q in oq_doc.get("questions") or []:
        if not isinstance(q, dict):
            raise FatalError(f"{QUESTIONS_FILE}: question must be a mapping")
        qid = _text(q.get("id"))
        cat = _text(q.get("category"))
        st = _text(q.get("status"))
        title = _text(q.get("title"))
        detail = _text(q.get("detail"))
        if not (qid and cat and st and title and detail):
            raise FatalError(f"{QUESTIONS_FILE}: question {qid!r} missing required fields")
        if qid in oq_ids:
            raise FatalError(f"{QUESTIONS_FILE}: duplicate open question id '{qid}'")
        if st not in ("open", "resolved"):
            raise FatalError(f"{QUESTIONS_FILE}: question '{qid}' invalid status {st!r}")
        res = _text(q.get("resolution"))
        res_on_txt = _text(q.get("resolved_on"))
        res_on: _dt.date | None = None
        if res_on_txt is not None:
            res_on = _dt.date.fromisoformat(res_on_txt)
        if st == "resolved" and (res is None or res_on is None):
            raise FatalError(f"{QUESTIONS_FILE}: resolved question '{qid}' requires resolution and resolved_on")
        if st == "open" and (res is not None or res_on is not None):
            raise FatalError(f"{QUESTIONS_FILE}: open question '{qid}' cannot have resolution or resolved_on")

        affects = q.get("affects")
        open_questions.append(
            {
                "oq_id": qid,
                "category": cat,
                "status": st,
                "title": title,
                "detail": detail,
                "affects_raw": [str(a) for a in affects] if isinstance(affects, list) else None,
                "resolve_via": _text(q.get("resolve_via")),
                "resolution": res,
                "resolved_on": res_on,
            }
        )
        oq_ids.add(qid)

    # Step 6: Parse rule files -> rule, rule_condition, rule_item, rule_open_question, rule_item_open_question
    config_versions: dict[str, str] = {
        "status_definitions": st_cfg_ver,
        "open_questions": oq_cfg_ver,
    }
    review_statuses: set[str] = set()
    raw_rules_with_meta: list[tuple[str, str, dict[str, Any]]] = []

    for expected_pathway, rel in RULE_FILES:
        rdoc = yaml.safe_load((base / rel).read_text(encoding="utf-8"))
        if not isinstance(rdoc, dict):
            raise FatalError(f"{rel}: top level must be a mapping")
        cfg = rdoc.get("config") or {}
        if _text(cfg.get("pathway")) != expected_pathway:
            raise FatalError(f"{rel}: config.pathway must be {expected_pathway!r}")
        cver = _text(cfg.get("config_version"))
        if not cver:
            raise FatalError(f"{rel}: missing config.config_version")
        config_versions[expected_pathway] = cver
        crs = _text(cfg.get("clinical_review_status")) or "not_reviewed"
        review_statuses.add(crs)
        rlist = rdoc.get("rules")
        if not isinstance(rlist, list) or not rlist:
            raise FatalError(f"{rel}: rules must be a non-empty list")
        for raw in rlist:
            if not isinstance(raw, dict):
                raise FatalError(f"{rel}: rule entry must be a mapping")
            raw_rules_with_meta.append((expected_pathway, f"data-pipeline/rules/{rel}", raw))

    if len(review_statuses) != 1:
        raise FatalError(
            f"clinical_review_status mismatch across rule files: {sorted(review_statuses)}"
        )
    clinical_review_status = next(iter(review_statuses))

    # Check if WCV-TIMING-DUE-WINDOW is verified and unflagged
    wcv_due_window_auth = False
    for _, _, raw in raw_rules_with_meta:
        if _text(raw.get("rule_id")) == "WCV-TIMING-DUE-WINDOW":
            wcv_due_window_auth = (
                _text(raw.get("verification_status")) == "verified"
                and raw.get("requires_clinical_review") is False
            )

    rules: list[dict[str, Any]] = []
    conditions: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    rule_oqs: list[dict[str, Any]] = []
    item_oqs: list[dict[str, Any]] = []
    seen_rule_ids: set[str] = set()
    used_std_keys: set[tuple[str, str]] = set()

    for expected_pathway, yaml_path, raw in raw_rules_with_meta:
        rid = _text(raw.get("rule_id"))
        where = f"{yaml_path}: rule '{rid}'"
        if not rid:
            raise FatalError(f"{yaml_path}: rule missing rule_id")
        if rid in seen_rule_ids:
            raise FatalError(f"{where}: duplicate rule_id '{rid}'")
        seen_rule_ids.add(rid)

        missing = [
            k
            for k in REQUIRED_RULE_METADATA
            if k not in raw
            or (k not in ("effective_date", "requires_clinical_review") and _text(raw.get(k)) is None)
        ]
        if missing:
            raise FatalError(f"{where}: missing mandatory metadata: {', '.join(missing)}")

        unknown = sorted(set(raw) - set(REQUIRED_RULE_METADATA) - set(OPTIONAL_RULE_KEYS))
        if unknown:
            raise FatalError(f"{where}: unknown key(s): {', '.join(unknown)}")

        pathway = _text(raw["pathway"])
        if pathway != expected_pathway:
            raise FatalError(f"{where}: pathway {pathway!r} != {expected_pathway!r}")

        rver = _text(raw["rule_version"]) or ""
        ver_major, ver_minor, ver_patch = parse_semver(rver, where)

        sname = _text(raw["source_name"]) or ""
        sver = _text(raw["source_version"]) or ""
        if (sname, sver) not in std_keys:
            raise FatalError(f"{where}: unregistered source ({sname!r}, {sver!r})")
        used_std_keys.add((sname, sver))

        vstatus = _text(raw["verification_status"]) or ""
        if vstatus not in ALLOWED_VERIFICATION_STATUSES:
            raise FatalError(f"{where}: invalid verification_status {vstatus!r}")

        req_review = _strict_bool(
            raw["requires_clinical_review"], "requires_clinical_review", where
        )
        if vstatus == "unresolved" and not req_review:
            raise FatalError(
                f"{where}: verification_status='unresolved' requires requires_clinical_review=true (LV-3)"
            )

        eff_t, eff_p, eff_f = parse_partial_date(
            raw.get("effective_date"), field_name="effective_date", where=where
        )
        eff_note = _text(raw.get("effective_date_note"))
        if eff_p == "unknown" and not eff_note:
            raise FatalError(f"{where}: effective_date is null/unknown without effective_date_note")

        last_rev_txt = _text(raw.get("last_reviewed"))
        if not last_rev_txt or not _DATE.match(last_rev_txt):
            raise FatalError(f"{where}: invalid last_reviewed {last_rev_txt!r}")
        last_reviewed = _dt.date.fromisoformat(last_rev_txt)

        # Open questions on rule
        raw_oqs = raw.get("open_question_ids") or []
        if not isinstance(raw_oqs, list):
            raise FatalError(f"{where}: open_question_ids must be a list")
        seen_oq_for_rule: set[str] = set()
        for q in raw_oqs:
            qstr = _text(q)
            if not qstr or qstr not in oq_ids:
                raise FatalError(f"{where}: unknown open_question_id {q!r}")
            if qstr in seen_oq_for_rule:
                raise FatalError(f"{where}: duplicate open_question_id '{qstr}' on rule")
            seen_oq_for_rule.add(qstr)
            rule_oqs.append({"rule_id": rid, "rule_version": rver, "oq_id": qstr})

        if vstatus == "unresolved" and not seen_oq_for_rule:
            raise FatalError(f"{where}: unresolved rule must cite at least one open_question_id")
        if req_review and not seen_oq_for_rule:
            raise FatalError(
                f"{where}: requires_clinical_review rule must cite at least one open_question_id"
            )

        spec = raw.get("spec")
        if spec is None:
            spec = {}
        elif not isinstance(spec, dict):
            raise FatalError(f"{where}: spec must be a mapping")

        for bflag in ("one_time", "is_diagnosis", "is_screening_result_only"):
            if bflag in spec:
                _strict_bool(spec[bflag], f"spec.{bflag}", where)

        # Verify spec.timing.open_question_ids is subset of rule-level open_question_ids (§2.11)
        timing_block = spec.get("timing")
        if isinstance(timing_block, dict) and "open_question_ids" in timing_block:
            timing_oqs = set(timing_block.get("open_question_ids") or [])
            if not timing_oqs <= seen_oq_for_rule:
                raise FatalError(
                    f"{where}: spec.timing.open_question_ids {sorted(timing_oqs)} is not a subset of rule open_question_ids"
                )

        # Conditions (§2.9)
        elig = spec.get("eligibility")
        if isinstance(elig, dict) and "conditions" in elig:
            raw_conds = elig.get("conditions")
            if not isinstance(raw_conds, list):
                raise FatalError(f"{where}: spec.eligibility.conditions must be a list")
            for c_ord, c in enumerate(raw_conds, 1):
                cwhere = f"{where}, condition[{c_ord}]"
                if not isinstance(c, dict):
                    raise FatalError(f"{cwhere}: condition must be a mapping")
                kind = _text(c.get("kind"))
                if kind not in ("inclusion", "exclusion"):
                    raise FatalError(f"{cwhere}: condition kind {kind!r} not in ('inclusion', 'exclusion')")
                as_printed = _text(c.get("as_printed"))
                if not as_printed:
                    raise FatalError(f"{cwhere}: missing as_printed")
                if "machine_evaluable" not in c:
                    raise FatalError(f"{cwhere}: missing machine_evaluable")
                me = _strict_bool(c["machine_evaluable"], "machine_evaluable", cwhere)
                attr = _text(c.get("attribute"))
                req_val = c.get("required_value") if "required_value" in c else None
                if me:
                    if kind == "exclusion":
                        raise FatalError(f"{cwhere}: exclusion condition cannot have machine_evaluable=true")
                    if not attr or req_val is None:
                        raise FatalError(
                            f"{cwhere}: machine_evaluable=true requires attribute and non-null required_value"
                        )
                else:
                    if not req_review:
                        raise FatalError(
                            f"{cwhere}: machine_evaluable=false condition requires parent rule requires_clinical_review=true"
                        )
                conditions.append(
                    {
                        "rule_id": rid,
                        "rule_version": rver,
                        "condition_ordinal": c_ord,
                        "kind": kind,
                        "as_printed": as_printed,
                        "machine_evaluable": me,
                        "attribute": attr,
                        "required_value": _normalize_for_json(req_val),
                    }
                )

        projections = extract_rule_projections(
            raw, where, wcv_due_window_authoritative=wcv_due_window_auth
        )
        is_authoritative = (vstatus == "verified") and (not req_review)

        # Items (§2.10)
        # (a) Well-Child assessment/follow-up items
        seen_item_keys: set[tuple[str, str]] = set()
        for cat in ITEM_LIST_KEYS:
            raw_list = spec.get(cat)
            if raw_list is None:
                continue
            if not isinstance(raw_list, list):
                raise FatalError(f"{where}: spec.{cat} must be a list")
            for ordinal, item_raw in enumerate(raw_list, 1):
                iwhere = f"{where}, {cat}[{ordinal}]"
                if not isinstance(item_raw, dict):
                    raise FatalError(f"{iwhere}: item must be a mapping")
                icode = _text(item_raw.get("code"))
                idesc = _text(item_raw.get("description"))
                iref = _text(item_raw.get("source_reference"))
                istat = _text(item_raw.get("verification_status"))
                if not (icode and idesc and iref and istat):
                    raise FatalError(f"{iwhere}: item missing mandatory field(s)")
                if istat not in ALLOWED_VERIFICATION_STATUSES:
                    raise FatalError(f"{iwhere}: invalid item verification_status {istat!r}")
                if (cat, icode) in seen_item_keys:
                    raise FatalError(f"{iwhere}: duplicate item ({cat}, {icode}) in rule")
                seen_item_keys.add((cat, icode))

                ioqs = item_raw.get("open_question_ids") or []
                seen_ioq: set[str] = set()
                for q in ioqs:
                    qstr = _text(q)
                    if not qstr or qstr not in oq_ids:
                        raise FatalError(f"{iwhere}: unknown item open_question_id {q!r}")
                    if qstr in seen_ioq:
                        raise FatalError(f"{iwhere}: duplicate open_question_id '{qstr}' on item")
                    seen_ioq.add(qstr)
                    item_oqs.append(
                        {
                            "rule_id": rid,
                            "rule_version": rver,
                            "category": cat,
                            "code": icode,
                            "oq_id": qstr,
                        }
                    )
                if istat == "unresolved" and not seen_ioq:
                    raise FatalError(f"{iwhere}: unresolved item must cite at least one open_question_id")

                comps = item_raw.get("components")
                rrefs = item_raw.get("rule_refs")
                status_is_ver = istat == "verified"
                items.append(
                    {
                        "rule_id": rid,
                        "rule_version": rver,
                        "category": cat,
                        "code": icode,
                        "code_origin": "yaml",
                        "text_verbatim": None,
                        "ordinal": ordinal,
                        "description": idesc,
                        "source_reference": iref,
                        "inherited_from_rule": False,
                        "verification_status": istat,
                        "status_is_verified": status_is_ver,
                        "effective_authority": status_is_ver and is_authoritative,
                        "condition_text": _text(item_raw.get("condition")),
                        "components_text": [str(x) for x in comps] if comps else None,
                        "rule_refs": [str(x) for x in rrefs] if rrefs else None,
                        "notes": _text(item_raw.get("notes")),
                    }
                )

        # (b) IFHAS package components
        if _text(raw.get("rule_type")) == "screening_package":
            pkg_comps = spec.get("components")
            if not isinstance(pkg_comps, list) or not pkg_comps:
                raise FatalError(f"{where}: screening_package requires non-empty spec.components list")
            seen_slugs: dict[str, str] = {}
            for ordinal, comp_text in enumerate(pkg_comps, 1):
                if not isinstance(comp_text, str) or not comp_text.strip():
                    raise FatalError(f"{where}: component[{ordinal}] must be a non-empty string")
                slug = slugify_component(comp_text)
                if slug in seen_slugs:
                    raise FatalError(
                        f"{where}: component slug collision '{slug}' between {seen_slugs[slug]!r} and {comp_text!r}"
                    )
                seen_slugs[slug] = comp_text
                status_is_ver = vstatus == "verified"
                items.append(
                    {
                        "rule_id": rid,
                        "rule_version": rver,
                        "category": "package_component",
                        "code": slug,
                        "code_origin": "derived_slug",
                        "text_verbatim": comp_text,
                        "ordinal": ordinal,
                        "description": comp_text,
                        "source_reference": _text(raw["source_reference"]) or "",
                        "inherited_from_rule": True,
                        "verification_status": vstatus,
                        "status_is_verified": status_is_ver,
                        "effective_authority": status_is_ver and is_authoritative,
                        "condition_text": None,
                        "components_text": None,
                        "rule_refs": None,
                        "notes": None,
                    }
                )

        raw_hist = raw.get("history") if "history" in raw else None
        rule_row = {
            "rule_id": rid,
            "rule_version": rver,
            "ver_major": ver_major,
            "ver_minor": ver_minor,
            "ver_patch": ver_patch,
            "pathway": pathway,
            "rule_type": _text(raw.get("rule_type")),
            "source_name": sname,
            "source_version": sver,
            "source_reference": _text(raw["source_reference"]) or "",
            "verification_status": vstatus,
            "requires_clinical_review": req_review,
            "is_authoritative": is_authoritative,
            "effective_date_text": eff_t,
            "effective_date_precision": eff_p,
            "effective_date_from": eff_f,
            "effective_date_note": eff_note,
            "last_reviewed": last_reviewed,
            "description": _text(raw["description"]) or "",
            "notes": _text(raw.get("notes")),
            "spec": _normalize_for_json(spec),
            "history": _normalize_for_json(raw_hist) if raw_hist is not None else None,
            "content_sha256": compute_content_sha256(raw),
            "yaml_path": yaml_path,
            **projections,
        }
        rules.append(rule_row)

    # Validate soft rule_refs on items and standard usage
    if used_std_keys != std_keys:
        unused = std_keys - used_std_keys
        raise FatalError(f"standards in {SOURCES_FILE} not referenced by any rule: {sorted(unused)}")
    for item in items:
        for ref in item["rule_refs"] or []:
            if ref not in seen_rule_ids:
                raise FatalError(
                    f"rule '{item['rule_id']}', item '{item['code']}': rule_ref '{ref}' does not exist"
                )

    # LV-2 assertion: item effective authority implies parent rule is authoritative
    rule_auth_by_key = {(r["rule_id"], r["rule_version"]): r["is_authoritative"] for r in rules}
    for item in items:
        parent_auth = rule_auth_by_key[(item["rule_id"], item["rule_version"])]
        expected_eff = item["status_is_verified"] and parent_auth
        if item["effective_authority"] != expected_eff:
            raise FatalError(f"item {item['code']} effective_authority mismatch")
        if item["effective_authority"] and not parent_auth:
            raise FatalError(
                f"item {item['code']} under non-authoritative rule {item['rule_id']} cannot have effective_authority=true"
            )

    # LV-4: Expand pathway-level open_question.affects into derived links (kept separate from cited links)
    cited_pairs = {(roq["rule_id"], roq["oq_id"]) for roq in rule_oqs}
    derived_links: list[dict[str, str]] = []
    uncited_in_scope: dict[str, list[str]] = {}
    for oq in open_questions:
        qid = oq["oq_id"]
        for aff in oq["affects_raw"] or []:
            if aff in ("ifhas", "well_child"):
                for r in rules:
                    if r["pathway"] == aff and (r["rule_id"], qid) not in cited_pairs:
                        derived_links.append({"rule_id": r["rule_id"], "oq_id": qid})
                        uncited_in_scope.setdefault(qid, []).append(r["rule_id"])

    return ParsedClinicalBundle(
        loader_version=LOADER_VERSION,
        bundle_sha256=bundle_sha256,
        file_hashes=file_hashes,
        config_versions=config_versions,
        git_commit=git_commit_if_clean(repo_root()),
        clinical_review_status=clinical_review_status,
        standards=standards,
        verification_statuses=verification_statuses,
        evaluation_statuses=evaluation_statuses,
        reason_codes=reason_codes,
        guards=guards,
        open_questions=open_questions,
        rules=rules,
        conditions=conditions,
        items=items,
        rule_open_questions=rule_oqs,
        rule_item_open_questions=item_oqs,
        derived_pathway_links=derived_links,
        uncited_in_scope_rules=uncited_in_scope,
    )
