"""Synthetic fixtures. Nothing here encodes a real clinical threshold; values are
placeholders (e.g. 'SYN-A') used only to exercise loader mechanics."""

import copy
from pathlib import Path

import pytest
import yaml

from rule_loader import default_rules_dir

SOURCE = {
    "source_name": "Synthetic Test Standard",
    "source_version": "T1",
    "document_ref": "SYN/T1",
    "publication_date": "2000-01",
    "effective_date": "2000-01",
    "effective_date_note": None,
    "url": None,
}


def synthetic_rule(rule_id, pathway, **overrides):
    rule = {
        "rule_id": rule_id,
        "pathway": pathway,
        "rule_type": "synthetic",
        "rule_version": "1.0.0",
        "source_name": SOURCE["source_name"],
        "source_version": SOURCE["source_version"],
        "source_reference": "SYN/T1, section 0.0",
        "verification_status": "verified",
        "effective_date": "2000-01",
        "last_reviewed": "2000-02-01",
        "description": "Synthetic rule for loader tests.",
        "requires_clinical_review": False,
        "open_question_ids": [],
        "history": [],
        "spec": {},
    }
    rule.update(overrides)
    return rule


def _status_defs():
    real = yaml.safe_load((default_rules_dir() / "common" / "status_definitions.yaml").read_text())
    return real  # vocabulary only; contains no patient or threshold data


@pytest.fixture
def make_config(tmp_path):
    """Write a valid synthetic rules directory; return (path, mutable parts)."""

    def _make(ifhas_rules=None, wcv_rules=None, questions=None):
        parts = {
            "ifhas": [synthetic_rule("SYN-IFHAS-1", "ifhas")] if ifhas_rules is None else ifhas_rules,
            "well_child": [synthetic_rule("SYN-WCV-1", "well_child")] if wcv_rules is None else wcv_rules,
            "questions": questions
            if questions is not None
            else [{"id": "OQ-SYN-1", "category": "interpretation", "status": "open", "title": "t", "detail": "d"}],
        }
        for sub in ("common", "ifhas", "well_child"):
            (tmp_path / sub).mkdir(exist_ok=True)
        dump = lambda p, d: (tmp_path / p).write_text(yaml.safe_dump(d, sort_keys=False))
        dump("common/sources.yaml", {"sources": [copy.deepcopy(SOURCE)]})
        dump("common/status_definitions.yaml", _status_defs())
        dump("common/open_questions.yaml", {"questions": parts["questions"]})
        dump("ifhas/ifhas_rules.yaml", {"config": {"pathway": "ifhas", "config_version": "1.0.0"}, "rules": parts["ifhas"]})
        dump("well_child/well_child_rules.yaml", {"config": {"pathway": "well_child", "config_version": "1.0.0"}, "rules": parts["well_child"]})
        return Path(tmp_path)

    return _make
