"""Load and validate the IFHAS and Well-Child rule configuration.

Validation collects *every* problem and raises one RuleConfigError so that a
rule author can fix everything in a single pass.
"""

import datetime as _dt
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import yaml

from .errors import RuleConfigError, ValidationIssue
from .models import (
    ALLOWED_VERIFICATION_STATUSES,
    EVALUATION_STATUSES,
    ITEM_LIST_KEYS,
    OPTIONAL_RULE_KEYS,
    REQUIRED_RULE_METADATA,
    OpenQuestion,
    Rule,
    RuleBundle,
    RuleItem,
    RuleVersionRecord,
    Source,
)

# (pathway, relative path of the rules file)
RULE_FILES = (
    ("ifhas", "ifhas/ifhas_rules.yaml"),
    ("well_child", "well_child/well_child_rules.yaml"),
)
SOURCES_FILE = "common/sources.yaml"
STATUS_FILE = "common/status_definitions.yaml"
QUESTIONS_FILE = "common/open_questions.yaml"

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YEAR_MONTH = re.compile(r"^\d{4}-\d{2}$")


def default_rules_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "rules"


def _read_yaml(path: Path, issues: List[ValidationIssue], rel: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError:
        issues.append(ValidationIssue(rel, "file not found"))
        return None
    except yaml.YAMLError as exc:
        issues.append(ValidationIssue(rel, f"not valid YAML: {exc}"))
        return None
    if not isinstance(data, dict):
        issues.append(ValidationIssue(rel, "top level must be a mapping"))
        return None
    return data


def _text(value: Any) -> Optional[str]:
    """Normalise YAML scalars (dates, numbers) to strings; empty -> None."""
    if value is None:
        return None
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()[:10]
    text = str(value).strip()
    return text or None


def _valid_date(text: Optional[str], allow_year_month: bool) -> bool:
    if text is None:
        return False
    if _DATE.match(text):
        try:
            _dt.date.fromisoformat(text)
            return True
        except ValueError:
            return False
    return allow_year_month and bool(_YEAR_MONTH.match(text)) and 1 <= int(text[5:]) <= 12


# --------------------------------------------------------------------------- items
def _parse_items(
    spec: Dict[str, Any], where: str, issues: List[ValidationIssue], oq_ids: Set[str]
) -> List[RuleItem]:
    items: List[RuleItem] = []
    for key in ITEM_LIST_KEYS:
        raw_list = spec.get(key)
        if raw_list is None:
            continue
        if not isinstance(raw_list, list):
            issues.append(ValidationIssue(where, f"spec.{key} must be a list"))
            continue
        for n, raw in enumerate(raw_list, 1):
            label = f"{where}, {key}[{n}]"
            if not isinstance(raw, dict):
                issues.append(ValidationIssue(label, "item must be a mapping"))
                continue
            code = _text(raw.get("code"))
            label = f"{where}, item '{code or key + '[' + str(n) + ']'}'"
            ref = _text(raw.get("source_reference"))
            status = _text(raw.get("verification_status"))
            if not code:
                issues.append(ValidationIssue(label, "missing 'code'"))
            if not _text(raw.get("description")):
                issues.append(ValidationIssue(label, "missing 'description'"))
            if not ref:
                issues.append(ValidationIssue(label, "missing 'source_reference' (every clinical item must cite its source)"))
            if status not in ALLOWED_VERIFICATION_STATUSES:
                issues.append(ValidationIssue(
                    label, f"invalid verification_status {status!r}; allowed: {', '.join(ALLOWED_VERIFICATION_STATUSES)}"))
            oqs = tuple(raw.get("open_question_ids") or ())
            for q in oqs:
                if q not in oq_ids:
                    issues.append(ValidationIssue(label, f"unknown open question id '{q}'"))
            if status == "unresolved" and not oqs:
                issues.append(ValidationIssue(label, "unresolved items must reference at least one open_question_id"))
            items.append(RuleItem(
                category=key, code=code or "", description=_text(raw.get("description")) or "",
                source_reference=ref or "", verification_status=status or "",
                condition=_text(raw.get("condition")), components=tuple(raw.get("components") or ()),
                rule_refs=tuple(raw.get("rule_refs") or ()), open_question_ids=oqs, notes=_text(raw.get("notes")),
            ))
    return items


def _parse_history(raw_hist: Any, current_version: Optional[str], where: str,
                   issues: List[ValidationIssue]) -> List[RuleVersionRecord]:
    records: List[RuleVersionRecord] = []
    if raw_hist in (None, []):
        return records
    if not isinstance(raw_hist, list):
        issues.append(ValidationIssue(where, "history must be a list"))
        return records
    seen: Set[str] = set()
    for n, h in enumerate(raw_hist, 1):
        label = f"{where}, history[{n}]"
        if not isinstance(h, dict):
            issues.append(ValidationIssue(label, "history entry must be a mapping"))
            continue
        for key in ("rule_version", "source_reference", "verification_status", "last_reviewed", "change_summary"):
            if not _text(h.get(key)):
                issues.append(ValidationIssue(label, f"missing '{key}' (history must preserve the original source reference)"))
        ver = _text(h.get("rule_version")) or ""
        if ver and not _SEMVER.match(ver):
            issues.append(ValidationIssue(label, f"rule_version {ver!r} must look like 1.2.3"))
        if ver in seen:
            issues.append(ValidationIssue(label, f"duplicate history version {ver}"))
        if ver and ver == current_version:
            issues.append(ValidationIssue(label, f"history version {ver} equals the current rule_version; bump rule_version"))
        seen.add(ver)
        if _text(h.get("verification_status")) not in ALLOWED_VERIFICATION_STATUSES:
            issues.append(ValidationIssue(label, f"invalid verification_status {h.get('verification_status')!r}"))
        records.append(RuleVersionRecord(ver, _text(h.get("source_reference")) or "",
                                         _text(h.get("verification_status")) or "",
                                         _text(h.get("last_reviewed")) or "", _text(h.get("change_summary")) or ""))
    return records


# --------------------------------------------------------------------------- rules
def _validate_package_spec(spec: Dict[str, Any], where: str, issues: List[ValidationIssue]) -> None:
    age = (spec.get("eligibility") or {}).get("age")
    if not isinstance(age, dict) or "min_years" not in age or "max_years" not in age or not age.get("as_printed"):
        issues.append(ValidationIssue(where, "screening_package needs spec.eligibility.age with min_years, max_years and as_printed"))
    sex = (spec.get("eligibility") or {}).get("sex")
    if not sex or not set(sex) <= {"female", "male"}:
        issues.append(ValidationIssue(where, "screening_package needs spec.eligibility.sex as a list of 'female'/'male'"))
    freq = spec.get("frequency")
    if not isinstance(freq, dict) or freq.get("type") not in ("recurring", "once_per_lifetime") or not freq.get("as_printed"):
        issues.append(ValidationIssue(where, "screening_package needs spec.frequency with type 'recurring'|'once_per_lifetime' and as_printed"))
    elif freq["type"] == "recurring" and not (freq.get("interval") or {}).get("value"):
        issues.append(ValidationIssue(where, "recurring frequency needs interval.value and interval.unit"))


def _parse_rule(raw: Any, index: int, rel: str, expected_pathway: str, config_pathway: Optional[str],
                sources: Dict[Tuple[str, str], Source], source_names: Set[str], oq_ids: Set[str],
                issues: List[ValidationIssue]) -> Optional[Rule]:
    rid = _text(raw.get("rule_id")) if isinstance(raw, dict) else None
    where = f"{rel}: rule '{rid}'" if rid else f"{rel}: rule #{index}"
    if not isinstance(raw, dict):
        issues.append(ValidationIssue(where, "rule must be a mapping"))
        return None

    missing = [k for k in REQUIRED_RULE_METADATA if k not in raw or (k != "effective_date" and _text(raw.get(k)) is None)]
    if missing:
        issues.append(ValidationIssue(where, "missing mandatory metadata: " + ", ".join(missing)))
    unknown = sorted(set(raw) - set(REQUIRED_RULE_METADATA) - set(OPTIONAL_RULE_KEYS))
    for key in unknown:
        if key == "authoritative":
            issues.append(ValidationIssue(where, "'authoritative' must not be configured; it is derived from verification_status and requires_clinical_review"))
        else:
            issues.append(ValidationIssue(where, f"unknown key '{key}' (typo?)"))

    status = _text(raw.get("verification_status"))
    if status is not None and status not in ALLOWED_VERIFICATION_STATUSES:
        issues.append(ValidationIssue(where, f"invalid verification_status {status!r}; allowed: {', '.join(ALLOWED_VERIFICATION_STATUSES)}"))

    pathway = _text(raw.get("pathway"))
    if pathway is not None and (pathway != expected_pathway or (config_pathway and pathway != config_pathway)):
        issues.append(ValidationIssue(where, f"pathway {pathway!r} does not match the file's pathway '{expected_pathway}'"))

    version = _text(raw.get("rule_version"))
    if version is not None and not _SEMVER.match(version):
        issues.append(ValidationIssue(where, f"rule_version {version!r} must look like 1.2.3"))

    eff = _text(raw.get("effective_date"))
    if "effective_date" in raw:
        if eff is None:
            if not _text(raw.get("effective_date_note")):
                issues.append(ValidationIssue(where, "effective_date is null; add 'effective_date_note' explaining why (e.g. standard states TBD)"))
        elif not _valid_date(eff, True):
            issues.append(ValidationIssue(where, f"effective_date {eff!r} must be YYYY-MM-DD, YYYY-MM or null"))
    reviewed = _text(raw.get("last_reviewed"))
    if reviewed is not None and not _valid_date(reviewed, False):
        issues.append(ValidationIssue(where, f"last_reviewed {reviewed!r} must be YYYY-MM-DD"))

    src_name, src_ver = _text(raw.get("source_name")), _text(raw.get("source_version"))
    if src_name and src_ver:
        if (src_name, src_ver) not in sources:
            hint = "unknown source_name" if src_name not in source_names else f"source_version {src_ver!r} not registered for this source"
            issues.append(ValidationIssue(where, f"{hint}; register it in {SOURCES_FILE}"))

    oqs = tuple(raw.get("open_question_ids") or ())
    for q in oqs:
        if q not in oq_ids:
            issues.append(ValidationIssue(where, f"unknown open question id '{q}'"))
    review = bool(raw.get("requires_clinical_review", False))
    if status == "unresolved" and not oqs:
        issues.append(ValidationIssue(where, "unresolved rules must reference at least one open_question_id"))
    if review and not oqs:
        issues.append(ValidationIssue(where, "requires_clinical_review rules must reference at least one open_question_id explaining why"))

    spec = raw.get("spec") or {}
    if not isinstance(spec, dict):
        issues.append(ValidationIssue(where, "spec must be a mapping"))
        spec = {}
    if raw.get("rule_type") == "screening_package":
        _validate_package_spec(spec, where, issues)
    items = _parse_items(spec, where, issues, oq_ids)
    history = _parse_history(raw.get("history"), version, where, issues)

    return Rule(
        rule_id=rid or "", pathway=pathway or "", rule_version=version or "", source_name=src_name or "",
        source_version=src_ver or "", source_reference=_text(raw.get("source_reference")) or "",
        verification_status=status or "", effective_date=eff, last_reviewed=reviewed or "",
        description=_text(raw.get("description")) or "", rule_type=_text(raw.get("rule_type")),
        effective_date_note=_text(raw.get("effective_date_note")), requires_clinical_review=review,
        open_question_ids=oqs, history=tuple(history), notes=_text(raw.get("notes")), spec=spec, items=tuple(items),
    )


# --------------------------------------------------------------------------- entry point
def load_rules(rules_dir: Optional[Path] = None) -> RuleBundle:
    """Load, validate and return all rules. Raises RuleConfigError listing every problem."""
    base = Path(rules_dir) if rules_dir is not None else default_rules_dir()
    issues: List[ValidationIssue] = []

    src_data = _read_yaml(base / SOURCES_FILE, issues, SOURCES_FILE) or {}
    sources: List[Source] = []
    for s in src_data.get("sources") or []:
        sources.append(Source(
            source_name=_text(s.get("source_name")) or "", source_version=_text(s.get("source_version")) or "",
            document_ref=_text(s.get("document_ref")) or "", publication_date=_text(s.get("publication_date")),
            effective_date=_text(s.get("effective_date")), effective_date_note=_text(s.get("effective_date_note")),
            url=_text(s.get("url"))))
    source_index = {(s.source_name, s.source_version): s for s in sources}
    source_names = {s.source_name for s in sources}

    oq_data = _read_yaml(base / QUESTIONS_FILE, issues, QUESTIONS_FILE) or {}
    questions: Dict[str, OpenQuestion] = {}
    for q in oq_data.get("questions") or []:
        qid = _text(q.get("id"))
        if not qid:
            issues.append(ValidationIssue(QUESTIONS_FILE, "question without id"))
            continue
        if qid in questions:
            issues.append(ValidationIssue(QUESTIONS_FILE, f"duplicate open question id '{qid}'"))
        questions[qid] = OpenQuestion(qid, _text(q.get("category")) or "", _text(q.get("status")) or "",
                                      _text(q.get("title")) or "", _text(q.get("detail")) or "",
                                      tuple(q.get("affects") or ()), _text(q.get("resolve_via")))

    st_data = _read_yaml(base / STATUS_FILE, issues, STATUS_FILE) or {}
    defined = tuple(s.get("id") for s in st_data.get("evaluation_statuses") or [])
    missing_st = [s for s in EVALUATION_STATUSES if s not in defined]
    if missing_st:
        issues.append(ValidationIssue(STATUS_FILE, "missing evaluation status definition(s): " + ", ".join(missing_st)))
    ver_defined = tuple(s.get("id") for s in st_data.get("verification_statuses") or [])
    if set(ver_defined) != set(ALLOWED_VERIFICATION_STATUSES):
        issues.append(ValidationIssue(STATUS_FILE, f"verification_statuses must be exactly {list(ALLOWED_VERIFICATION_STATUSES)}"))

    rules: List[Rule] = []
    locations: Dict[str, str] = {}
    config_versions: Dict[str, str] = {}
    for pathway, rel in RULE_FILES:
        data = _read_yaml(base / rel, issues, rel)
        if data is None:
            continue
        cfg = data.get("config") or {}
        cfg_pathway = _text(cfg.get("pathway"))
        if cfg_pathway != pathway:
            issues.append(ValidationIssue(rel, f"config.pathway is {cfg_pathway!r}, expected '{pathway}'"))
        config_versions[pathway] = _text(cfg.get("config_version")) or ""
        raw_rules = data.get("rules")
        if not isinstance(raw_rules, list) or not raw_rules:
            issues.append(ValidationIssue(rel, "'rules' must be a non-empty list"))
            continue
        for n, raw in enumerate(raw_rules, 1):
            rule = _parse_rule(raw, n, rel, pathway, cfg_pathway, source_index, source_names, set(questions), issues)
            if rule is None:
                continue
            if rule.rule_id:
                if rule.rule_id in locations:
                    issues.append(ValidationIssue(
                        f"{rel}: rule '{rule.rule_id}'", f"duplicate rule_id (first defined in {locations[rule.rule_id]})"))
                    continue
                locations[rule.rule_id] = rel
            rules.append(rule)

    # cross references (second pass)
    for rule in rules:
        for item in rule.items:
            for ref in item.rule_refs:
                if ref not in locations:
                    issues.append(ValidationIssue(f"rule '{rule.rule_id}', item '{item.code}'", f"rule_ref '{ref}' does not exist"))

    if issues:
        raise RuleConfigError(issues)
    return RuleBundle(rules=tuple(rules), open_questions=questions, sources=tuple(sources),
                      evaluation_statuses=defined, status_definitions=st_data, config_versions=config_versions)
