"""Central role -> permission matrix (docs/authentication-and-rbac.md §3).

Routers depend on permissions (`app.core.auth.require`), never on role names. Patient-level data
additionally passes through the caller's patient scope (organization + assignment or self link),
so a permission alone never grants access to another organization's or another person's records.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    POPULATION_HEALTH_MANAGER = "POPULATION_HEALTH_MANAGER"
    CARE_COORDINATOR = "CARE_COORDINATOR"
    CLINICIAN = "CLINICIAN"
    PATIENT = "PATIENT"


STAFF_ROLES = frozenset(
    {Role.POPULATION_HEALTH_MANAGER, Role.CARE_COORDINATOR, Role.CLINICIAN}
)
# Roles an organization administrator may assign through the admin API (patients are only
# created through the verified account-linking workflow).
ASSIGNABLE_ROLES = frozenset(
    {Role.SYSTEM_ADMIN, Role.POPULATION_HEALTH_MANAGER, Role.CARE_COORDINATOR, Role.CLINICIAN}
)

# Default patient access per role when a membership is created ("organization" = every patient
# of the organization, "assigned" = explicitly assigned patients only).
DEFAULT_PATIENT_ACCESS = {
    Role.SYSTEM_ADMIN: "assigned",
    Role.POPULATION_HEALTH_MANAGER: "organization",
    Role.CARE_COORDINATOR: "assigned",
    Role.CLINICIAN: "assigned",
    Role.PATIENT: "assigned",
}

ALL_PERMISSIONS = frozenset(
    {
        "users.read",
        "users.create",
        "users.update",
        "users.deactivate",
        "organizations.manage",
        "assignments.manage",
        "patient_links.invite",
        "patient_links.manage",
        "patients.read",
        "patients.read_assigned",
        "patients.read_self",
        "care_gaps.read",
        "care_gaps.review",
        "care_gaps.complete",
        "evaluations.read",
        "evaluations.run",
        "appointments.read",
        "appointments.create",
        "appointments.update",
        "referrals.read",
        "referrals.create",
        "referrals.update",
        "followups.read",
        "followups.create",
        "followups.update",
        "followups.respond",
        "patient_requests.create",
        "patient_requests.manage",
        "outreach.draft",
        "outreach.review",
        "ai.explain",
        "audit_logs.read",
        "insights.read",
        "facilities.read",
        "rules.read",
        "rules.manage",
        "platform.status",
        # Geospatial population intelligence (docs/geospatial-population-intelligence.md).
        "population.read",
        "population.alerts.read",
        "population.alerts.manage",
        "population.refresh",
        "population.configure",
    }
)

_CLINICAL_READ = frozenset(
    {
        "patients.read_assigned",
        "care_gaps.read",
        "evaluations.read",
        "appointments.read",
        "referrals.read",
        "followups.read",
        "insights.read",
        "facilities.read",
        "rules.read",
        "ai.explain",
        "platform.status",
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    # Platform/organization administration only. No patient-data permissions by default.
    Role.SYSTEM_ADMIN: frozenset(
        {
            "users.read",
            "users.create",
            "users.update",
            "users.deactivate",
            "organizations.manage",
            "assignments.manage",
            "patient_links.manage",
            "audit_logs.read",
            "facilities.read",
            "rules.read",
            "rules.manage",
            "platform.status",
            # Aggregation operations and thresholds only; no access to population data itself.
            "population.refresh",
            "population.configure",
        }
    ),
    Role.POPULATION_HEALTH_MANAGER: _CLINICAL_READ
    | {
        "population.read",
        "population.alerts.read",
        "population.alerts.manage",
        "population.refresh",
        "population.configure",
        "patients.read",
        "care_gaps.review",
        "evaluations.run",
        "followups.create",
        "followups.update",
        "patient_requests.manage",
        "patient_links.invite",
        "assignments.manage",
    },
    Role.CARE_COORDINATOR: _CLINICAL_READ
    | {
        "care_gaps.review",
        "care_gaps.complete",
        "appointments.create",
        "appointments.update",
        "referrals.create",
        "referrals.update",
        "followups.create",
        "followups.update",
        "patient_requests.manage",
        "patient_links.invite",
        "outreach.draft",
        "outreach.review",
    },
    Role.CLINICIAN: _CLINICAL_READ
    | {
        "population.read",
        "population.alerts.read",
        "care_gaps.review",
        "care_gaps.complete",
        "evaluations.run",
        "appointments.update",
        "referrals.create",
        "referrals.update",
        "followups.create",
    },
    # Self-service only; the patient scope is the single linked patient record.
    Role.PATIENT: frozenset(
        {"patients.read_self", "followups.respond", "patient_requests.create", "facilities.read"}
    ),
}

assert all(p <= ALL_PERMISSIONS for p in ROLE_PERMISSIONS.values())  # noqa: S101


def permissions_for(role: str, patient_access: str = "assigned") -> frozenset[str]:
    perms = ROLE_PERMISSIONS.get(Role(role), frozenset())
    if patient_access == "organization" and "patients.read_assigned" in perms:
        perms = perms | {"patients.read"}
    return perms
