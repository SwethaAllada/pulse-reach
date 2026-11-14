import pytest

from rule_loader import NonAuthoritativeRuleError, RuleConfigError, load_rules

from conftest import synthetic_rule

# --------------------------------------------------------------------------
# 1. Successful loading
# --------------------------------------------------------------------------


def test_synthetic_config_loads(make_config):
    bundle = load_rules(make_config())
    assert {r.rule_id for r in bundle.rules} == {"SYN-IFHAS-1", "SYN-WCV-1"}
    assert bundle.get("SYN-IFHAS-1").is_authoritative


def test_real_config_loads_both_pathways():
    bundle = load_rules()
    assert len(bundle.by_pathway("ifhas")) > 0
    assert len(bundle.by_pathway("well_child")) > 0
    assert set(bundle.evaluation_statuses) >= {
        "eligible", "not_eligible", "due", "upcoming", "overdue", "completed",
        "unknown", "insufficient_information", "requires_clinical_review",
    }


# --------------------------------------------------------------------------
# 2. Missing mandatory metadata
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["rule_id", "pathway", "rule_version", "source_name", "source_version", "source_reference",
     "verification_status", "effective_date", "last_reviewed", "description"],
)
def test_missing_mandatory_metadata_is_reported(make_config, field):
    rule = synthetic_rule("SYN-IFHAS-1", "ifhas")
    del rule[field]
    path = make_config(ifhas_rules=[rule])
    with pytest.raises(RuleConfigError) as exc:
        load_rules(path)
    assert field in str(exc.value)
    assert "missing mandatory metadata" in str(exc.value)


def test_null_effective_date_requires_explanation(make_config):
    bad = synthetic_rule("SYN-WCV-1", "well_child", effective_date=None)
    with pytest.raises(RuleConfigError, match="effective_date_note"):
        load_rules(make_config(wcv_rules=[bad]))
    ok = synthetic_rule("SYN-WCV-1", "well_child", effective_date=None, effective_date_note="standard states TBD")
    assert load_rules(make_config(wcv_rules=[ok])).get("SYN-WCV-1").effective_date is None


def test_all_problems_are_reported_together(make_config):
    r1 = synthetic_rule("SYN-IFHAS-1", "ifhas", verification_status="maybe")
    r2 = synthetic_rule("SYN-IFHAS-2", "ifhas", rule_version="one")
    with pytest.raises(RuleConfigError) as exc:
        load_rules(make_config(ifhas_rules=[r1, r2]))
    assert len(exc.value.issues) == 2


# --------------------------------------------------------------------------
# 3. Duplicate rule IDs
# --------------------------------------------------------------------------


def test_duplicate_rule_id_within_file(make_config):
    dup = [synthetic_rule("SYN-DUP", "ifhas"), synthetic_rule("SYN-DUP", "ifhas")]
    with pytest.raises(RuleConfigError, match="duplicate rule_id"):
        load_rules(make_config(ifhas_rules=dup))


def test_duplicate_rule_id_across_pathways(make_config):
    with pytest.raises(RuleConfigError, match="duplicate rule_id"):
        load_rules(make_config(ifhas_rules=[synthetic_rule("SYN-SAME", "ifhas")],
                               wcv_rules=[synthetic_rule("SYN-SAME", "well_child")]))


# --------------------------------------------------------------------------
# 4. Invalid verification status
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["confirmed", "VERIFIED", "", "pending"])
def test_invalid_verification_status(make_config, bad):
    rule = synthetic_rule("SYN-IFHAS-1", "ifhas", verification_status=bad)
    with pytest.raises(RuleConfigError) as exc:
        load_rules(make_config(ifhas_rules=[rule]))
    assert "verification_status" in str(exc.value) or "missing mandatory" in str(exc.value)


def test_invalid_item_status(make_config):
    rule = synthetic_rule("SYN-WCV-1", "well_child", spec={"preventive_assessments": [
        {"code": "x", "description": "d", "source_reference": "s", "verification_status": "nope"}]})
    with pytest.raises(RuleConfigError, match="invalid verification_status"):
        load_rules(make_config(wcv_rules=[rule]))


def test_unresolved_rule_must_cite_an_open_question(make_config):
    rule = synthetic_rule("SYN-IFHAS-1", "ifhas", verification_status="unresolved")
    with pytest.raises(RuleConfigError, match="open_question_id"):
        load_rules(make_config(ifhas_rules=[rule]))


def test_authority_cannot_be_configured(make_config):
    rule = synthetic_rule("SYN-IFHAS-1", "ifhas", verification_status="unresolved",
                          open_question_ids=["OQ-SYN-1"], authoritative=True)
    with pytest.raises(RuleConfigError, match="must not be configured"):
        load_rules(make_config(ifhas_rules=[rule]))


# --------------------------------------------------------------------------
# 5. Unresolved rules are blocked from authoritative evaluation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["unresolved", "reported"])
def test_non_verified_rules_are_blocked(make_config, status):
    rule = synthetic_rule("SYN-IFHAS-1", "ifhas", verification_status=status, open_question_ids=["OQ-SYN-1"])
    bundle = load_rules(make_config(ifhas_rules=[rule]))
    r = bundle.get("SYN-IFHAS-1")
    assert not r.is_authoritative
    with pytest.raises(NonAuthoritativeRuleError, match="SYN-IFHAS-1"):
        r.require_authoritative()
    with pytest.raises(NonAuthoritativeRuleError):
        bundle.require_authoritative("SYN-IFHAS-1")
    assert r not in bundle.authoritative_rules()


def test_verified_rule_flagged_for_review_is_blocked(make_config):
    rule = synthetic_rule("SYN-IFHAS-1", "ifhas", requires_clinical_review=True, open_question_ids=["OQ-SYN-1"])
    r = load_rules(make_config(ifhas_rules=[rule])).get("SYN-IFHAS-1")
    assert not r.is_authoritative
    with pytest.raises(NonAuthoritativeRuleError, match="requires_clinical_review"):
        r.require_authoritative()


def test_unresolved_item_is_blocked_but_rule_is_not(make_config):
    items = [
        {"code": "ok", "description": "d", "source_reference": "s", "verification_status": "verified"},
        {"code": "bad", "description": "d", "source_reference": "s", "verification_status": "unresolved",
         "open_question_ids": ["OQ-SYN-1"]},
    ]
    r = load_rules(make_config(wcv_rules=[synthetic_rule("SYN-WCV-1", "well_child", spec={"preventive_assessments": items})])).get("SYN-WCV-1")
    assert r.is_authoritative
    assert [i.code for i in r.authoritative_items] == ["ok"]
    with pytest.raises(NonAuthoritativeRuleError):
        r.unresolved_items[0].require_authoritative()


def test_real_unresolved_rules_are_blocked():
    bundle = load_rules()
    for rid in ("IFHAS-PROG-AGE-CEILING", "WCV-TIMING-DUE-WINDOW", "WCV-PROG-EFFECTIVE-DATE-TBD"):
        assert bundle.get(rid).verification_status == "unresolved"
        with pytest.raises(NonAuthoritativeRuleError):
            bundle.require_authoritative(rid)
    # Verified transcription but ambiguous/conflicting criteria -> still blocked.
    for rid in ("IFHAS-PKG-LUNG-LDCT-55-75", "IFHAS-PKG-LIQUID-BIOPSY-40-75",
                "IFHAS-PKG-CERVICAL-PAP-25-29", "IFHAS-PKG-CERVICAL-HPV-30-65"):
        assert not bundle.get(rid).is_authoritative


# --------------------------------------------------------------------------
# Versioning, references and source registry
# --------------------------------------------------------------------------


def test_history_must_preserve_source_reference(make_config):
    rule = synthetic_rule("SYN-IFHAS-1", "ifhas", rule_version="1.1.0",
                          history=[{"rule_version": "1.0.0", "verification_status": "verified",
                                    "last_reviewed": "2000-01-01", "change_summary": "c"}])
    with pytest.raises(RuleConfigError, match="source_reference"):
        load_rules(make_config(ifhas_rules=[rule]))


def test_history_is_preserved_on_the_rule(make_config):
    hist = {"rule_version": "1.0.0", "source_reference": "SYN/T1, old", "verification_status": "reported",
            "last_reviewed": "2000-01-01", "change_summary": "verified against source"}
    r = load_rules(make_config(ifhas_rules=[synthetic_rule("SYN-IFHAS-1", "ifhas", rule_version="1.1.0", history=[hist])])).get("SYN-IFHAS-1")
    assert r.history[0].rule_version == "1.0.0" and r.history[0].source_reference == "SYN/T1, old"


def test_history_version_cannot_equal_current(make_config):
    hist = {"rule_version": "1.0.0", "source_reference": "s", "verification_status": "verified",
            "last_reviewed": "2000-01-01", "change_summary": "c"}
    with pytest.raises(RuleConfigError, match="equals the current rule_version"):
        load_rules(make_config(ifhas_rules=[synthetic_rule("SYN-IFHAS-1", "ifhas", history=[hist])]))


def test_unknown_source_and_unknown_question_are_reported(make_config):
    rule = synthetic_rule("SYN-IFHAS-1", "ifhas", source_name="Made Up", open_question_ids=["OQ-NOPE"])
    with pytest.raises(RuleConfigError) as exc:
        load_rules(make_config(ifhas_rules=[rule]))
    assert "unknown source_name" in str(exc.value) and "OQ-NOPE" in str(exc.value)


def test_pathway_must_match_file(make_config):
    with pytest.raises(RuleConfigError, match="does not match the file's pathway"):
        load_rules(make_config(ifhas_rules=[synthetic_rule("SYN-IFHAS-1", "well_child")]))


def test_typo_in_key_is_reported(make_config):
    rule = synthetic_rule("SYN-IFHAS-1", "ifhas")
    rule["verfication_status"] = "verified"
    with pytest.raises(RuleConfigError, match="unknown key 'verfication_status'"):
        load_rules(make_config(ifhas_rules=[rule]))


# --------------------------------------------------------------------------
# 6. Package-specific age bands and frequencies (transcribed from IFHAS
#    Appendix 7, PDF pp.19-22: rule_id -> (min, max, sexes, frequency printed))
# --------------------------------------------------------------------------

MF = ("female", "male")
APPENDIX_7 = {
    "IFHAS-PKG-MAJOR-18-39": (18, 39, MF, "Every 3 years"),
    "IFHAS-PKG-MAJOR-40-64": (40, 64, MF, "Every 3 years"),
    "IFHAS-PKG-MAJOR-65-75": (65, 75, MF, "Every 3 years"),
    "IFHAS-PKG-VISION-40-75": (40, 75, MF, "Annually"),
    "IFHAS-PKG-HEARING-DEMENTIA-50-64": (50, 64, MF, "Every 3 years"),
    "IFHAS-PKG-HEARING-DEMENTIA-65-75": (65, 75, MF, "Annually"),
    "IFHAS-PKG-ORAL-18-75": (18, 75, MF, "Annually"),
    "IFHAS-PKG-CERVICAL-PAP-25-29": (25, 29, ("female",), "Every 3 years"),
    "IFHAS-PKG-CERVICAL-HPV-30-65": (30, 65, ("female",), "Every 5 years"),
    "IFHAS-PKG-BREAST-CBE-20-34": (20, 34, ("female",), "Every 3 years"),
    "IFHAS-PKG-BREAST-CBE-GAIL-35-39": (35, 39, ("female",), "Every 3 years"),
    "IFHAS-PKG-MAMMOGRAPHY-40-75": (40, 75, ("female",), "Every 2 years"),
    "IFHAS-PKG-FEMALE-REPRO-20-35": (20, 35, ("female",), "Every 3 years"),
    "IFHAS-PKG-MALE-REPRO-20-35": (20, 35, ("male",), "Every 3 years"),
    "IFHAS-PKG-FIT-40-75": (40, 75, MF, "Annually"),
    "IFHAS-PKG-LIQUID-BIOPSY-40-75": (40, 75, MF, "Every 3 years"),
    "IFHAS-PKG-COLONOSCOPY-40-75": (40, 75, MF, "Every 10 years"),
    "IFHAS-PKG-DEXA-60-75": (60, 75, MF, "Every 2 years"),
    "IFHAS-PKG-LUNG-LDCT-55-75": (55, 75, MF, "Annually"),
    "IFHAS-PKG-AAA-M-65-75": (65, 75, ("male",), "Once in a lifetime"),
}


def test_exactly_twenty_packages_encoded():
    packages = load_rules().by_type("screening_package", "ifhas")
    assert len(packages) == 20
    assert {p.rule_id for p in packages} == set(APPENDIX_7)


@pytest.mark.parametrize("rule_id", sorted(APPENDIX_7))
def test_package_age_band_sex_and_frequency_preserved(rule_id):
    lo, hi, sexes, freq_printed = APPENDIX_7[rule_id]
    rule = load_rules().get(rule_id)
    assert (rule.age_range.min_years, rule.age_range.max_years) == (lo, hi)
    assert tuple(sorted(rule.sexes)) == tuple(sorted(sexes))
    assert rule.frequency.as_printed == freq_printed
    assert rule.frequency.is_one_time == (freq_printed == "Once in a lifetime")
    assert rule.spec["one_time"] == rule.frequency.is_one_time


def test_recurring_intervals_match_printed_frequency():
    words = {"Annually": (1, "years"), "Every 2 years": (2, "years"), "Every 3 years": (3, "years"),
             "Every 5 years": (5, "years"), "Every 10 years": (10, "years")}
    for rule_id, (_, _, _, printed) in APPENDIX_7.items():
        f = load_rules().get(rule_id).frequency
        if printed in words:
            assert (f.interval_value, f.interval_unit) == words[printed]
        else:
            assert f.interval_value is None


def test_no_universal_rule_above_75_is_encoded():
    bundle = load_rules()
    assert all(p.age_range.max_years <= 75 for p in bundle.by_type("screening_package", "ifhas"))
    ceiling = bundle.get("IFHAS-PROG-AGE-CEILING")
    assert ceiling.verification_status == "unresolved"
    assert "min_years" not in ceiling.spec and "max_years" not in ceiling.spec
    assert bundle.get("IFHAS-PROG-ELIG-MIN-AGE").spec["max_years"] is None


def test_conditional_packages_keep_verbatim_criteria():
    bundle = load_rules()
    lung = bundle.get("IFHAS-PKG-LUNG-LDCT-55-75").spec["eligibility"]["conditions"]
    assert len(lung) == 3 and all(not c["machine_evaluable"] for c in lung)
    lb = bundle.get("IFHAS-PKG-LIQUID-BIOPSY-40-75").spec["eligibility"]["conditions"]
    assert [c["kind"] for c in lb] == ["inclusion", "exclusion", "exclusion", "exclusion"]
    aaa = bundle.get("IFHAS-PKG-AAA-M-65-75").spec["eligibility"]["conditions"][0]
    assert aaa["attribute"] == "smoking_history.ever_smoked"


# --------------------------------------------------------------------------
# 7. All 14 Well-Child visits (section 3.2.3 / Appendix 1)
# --------------------------------------------------------------------------

VISITS = [  # (rule suffix, label as printed, months)
    ("01M", "1 month", 1), ("02M", "2 months", 2), ("04M", "4 months", 4), ("06M", "6 months", 6),
    ("09M", "9 months", 9), ("12M", "12 months", 12), ("15M", "15 months", 15), ("18M", "18 months", 18),
    ("24M", "2 years", 24), ("30M", "2.5 years", 30), ("36M", "3 years", 36), ("48M", "4 years", 48),
    ("60M", "5 years", 60), ("72M", "6 years", 72),
]


def test_fourteen_visits_in_order():
    visits = load_rules().by_type("visit_schedule", "well_child")
    assert len(visits) == 14
    assert [v.rule_id for v in visits] == [f"WCV-VISIT-{s}" for s, _, _ in VISITS]
    assert [v.spec["visit_number"] for v in visits] == list(range(1, 15))


@pytest.mark.parametrize("suffix,label,months", VISITS)
def test_visit_definition_preserved(suffix, label, months):
    v = load_rules().get(f"WCV-VISIT-{suffix}")
    age = v.spec["timing"]["recommended_age"]
    assert (age["value"], age["unit"], age["as_printed"]) == (months, "months", label)
    # standard defines no due window: must stay null, never invented
    assert v.spec["timing"]["due_window"] is None
    assert v.spec["timing"]["due_window_status"] == "not_specified_by_standard"
    assert v.effective_date is None and "TBD" in v.effective_date_note
    assert v.spec["history_components"]["items"] and v.spec["counselling_elements"]["items"]
    assert {i.category for i in v.items} >= {"preventive_assessments", "developmental_assessments", "follow_up_requirements"}


def test_developmental_screening_schedule():
    bundle = load_rules()
    has = lambda sfx, code: any(i.code == code for i in bundle.get(f"WCV-VISIT-{sfx}").items)
    assert [s for s, _, _ in VISITS if has(s, "m_chat_r")] == ["18M", "24M"]
    assert [s for s, _, _ in VISITS if has(s, "idaq")] == ["18M"]
    assert [s for s, _, _ in VISITS if has(s, "cbc")] == ["12M", "15M", "18M"]
    assert [s for s, _, _ in VISITS if has(s, "blood_pressure")] == ["36M", "48M", "60M", "72M"]


def test_source_discrepancies_are_unresolved_items_not_silently_resolved():
    bundle = load_rules()
    def unresolved(sfx):
        return {i.code for i in bundle.get(f"WCV-VISIT-{sfx}").unresolved_items}
    assert unresolved("15M") == {"oral_examination"}
    assert unresolved("30M") == {"head_circumference"}
    assert unresolved("48M") == {"head_circumference", "developmental_milestones"}
    assert unresolved("12M") == set()


def test_effective_date_tbd_is_explicit():
    bundle = load_rules()
    assert bundle.get("WCV-PROG-EFFECTIVE-DATE-TBD").spec["effective_date_as_printed"] == "TBD"
    assert bundle.get("WCV-PROG-EFFECTIVE-DATE-TBD").spec["in_force_status"] == "not_confirmed"
    wcv_source = [s for s in bundle.sources if s.source_name == "Standard for Well-Child Visits"][0]
    assert wcv_source.effective_date is None and "TBD" in wcv_source.effective_date_note
    assert all(r.effective_date is None for r in bundle.by_pathway("well_child"))


def test_mchat_r_tiers_as_specified():
    b = load_rules()
    low, mod, high = (b.get(f"WCV-MCHATR-{t}") for t in ("LOW", "MODERATE", "HIGH"))
    assert [(r.spec["score"]["min"], r.spec["score"]["max"]) for r in (low, mod, high)] == [(0, 2), (3, 7), (8, None)]
    assert [a["window"]["value"] for a in mod.spec["actions"] if a["action"] == "refer"] == [4, 4]
    assert [a["window"]["value"] for a in high.spec["actions"] if a["action"] == "refer"] == [2, 2]
    for r in (low, mod, high):
        assert r.spec["is_diagnosis"] is False and r.spec["is_screening_result_only"] is True
    assert b.get("WCV-FU-REFERRAL-INITIATION-7D").spec["timing"]["value"] == 7
    assert (b.get("WCV-FU-SPECIALIST-EVALUATION-2-4W").spec["timing"]["min_value"],
            b.get("WCV-FU-SPECIALIST-EVALUATION-2-4W").spec["timing"]["max_value"]) == (2, 4)


# --------------------------------------------------------------------------
# 8. Source references present everywhere
# --------------------------------------------------------------------------


def test_every_rule_and_item_has_a_source_reference():
    bundle = load_rules()
    registered = {(s.source_name, s.source_version) for s in bundle.sources}
    for rule in bundle.rules:
        assert rule.source_reference.strip(), rule.rule_id
        assert (rule.source_name, rule.source_version) in registered, rule.rule_id
        assert rule.last_reviewed and rule.description and rule.rule_version, rule.rule_id
        for item in rule.items:
            assert item.source_reference.strip(), (rule.rule_id, item.code)
            assert item.verification_status in ("verified", "reported", "unresolved")


def test_source_references_cite_a_section_or_appendix():
    for rule in load_rules().rules:
        assert any(k in rule.source_reference for k in ("section", "Appendix", "document control")), rule.rule_id


def test_rule_ids_are_unique_and_open_questions_resolve():
    bundle = load_rules()
    ids = [r.rule_id for r in bundle.rules]
    assert len(ids) == len(set(ids))
    for rule in bundle.rules:
        assert all(q in bundle.open_questions for q in rule.open_question_ids)
