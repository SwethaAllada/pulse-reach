"""Validate Docker packaging includes YAML rules and data assets (`T-17`)."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_dockerfile_and_compose_include_rules_and_data():
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "data-pipeline/rules" in dockerfile
    assert "data/" in dockerfile
    assert "PULSE_REACH_REPO_ROOT" in dockerfile
    assert "RULES_DIR" in dockerfile
    assert "DATA_DIR" in dockerfile

    compose = yaml.safe_load(
        (repo_root / "infrastructure" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    backend_svc = compose["services"]["backend"]
    assert backend_svc["build"]["context"] == ".."
    assert backend_svc["build"]["dockerfile"] == "backend/Dockerfile"
    env = backend_svc["environment"]
    assert env["PULSE_REACH_REPO_ROOT"] == "/app"
    assert env["RULES_DIR"] == "/app/data-pipeline/rules"
    assert env["DATA_DIR"] == "/app/data"
    vols = backend_svc["volumes"]
    assert any("/app/data-pipeline/rules" in v for v in vols)
    assert any("/app/data" in v for v in vols)
