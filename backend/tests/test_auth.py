"""Authentication: login, tokens, refresh rotation/reuse, logout, reset, lockout, rate limits."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.models.identity import AuthSession, AuthToken, OneTimeToken, UserAccount
from app.services.identity import credentials
from app.services.identity.service import now
from app.services.identity.store import identity_session
from identity_fixtures import PW, client, users_mode, world  # noqa: F401

LOGIN = "/api/v1/auth/login"


def _login(email, password=PW, **extra):
    return client.post(LOGIN, json={"email": email, "password": password, **extra})


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_valid_login_returns_opaque_tokens_role_and_permissions(world):
    r = _login(world.emails["cc_a"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer" and body["role"] == "CARE_COORDINATOR"
    assert body["organization_id"] == world.org_a
    assert body["access_token"].startswith("pra_") and body["refresh_token"].startswith("prr_")
    assert 0 < body["expires_in"] <= settings.access_token_ttl_seconds
    assert "patients.read_assigned" in body["permissions"] and "patients.read" not in body["permissions"]
    assert "password" not in r.text.lower().replace("password_set", "")
    me = client.get("/api/v1/me", headers=_bearer(body["access_token"]))
    assert me.status_code == 200 and me.json()["user"]["email"] == world.emails["cc_a"]


def test_tokens_and_passwords_are_stored_only_as_hashes(world):
    body = _login(world.emails["cc_a"]).json()
    with identity_session() as s:
        hashes = set(s.scalars(select(AuthToken.token_hash)))
        user = s.scalars(select(UserAccount).where(UserAccount.email == world.emails["cc_a"])).one()
        assert body["access_token"] not in hashes and body["refresh_token"] not in hashes
        assert credentials.token_digest(body["access_token"]) in hashes
        assert user.password_hash.startswith("scrypt$") and PW not in user.password_hash


@pytest.mark.parametrize("email,password", [
    ("cc.a@test.pulsereach.invalid", "wrong-password-123"),
    ("nobody@test.pulsereach.invalid", PW),
])
def test_invalid_credentials_are_indistinguishable(world, email, password):
    r = _login(email, password)
    assert r.status_code == 401
    assert r.json()["error"]["message_key"] == "auth.invalid_credentials"


def test_disabled_account_cannot_login_and_existing_token_stops_working(world):
    tok = world.login("cc_a")["access_token"]
    assert client.get("/api/v1/me", headers=_bearer(tok)).status_code == 200
    r = client.post(f"/api/v1/admin/users/{world.users['cc_a']}/deactivate", headers=world.h("admin_a"))
    assert r.status_code == 200 and r.json()["scope"] == "account"
    assert client.get("/api/v1/me", headers=_bearer(tok)).status_code == 401
    assert _login(world.emails["cc_a"]).status_code == 401
    client.post(f"/api/v1/admin/users/{world.users['cc_a']}/activate", headers=world.h("admin_a"))
    assert _login(world.emails["cc_a"]).status_code == 200


def test_expired_access_token_is_rejected(world):
    tok = world.login("cc_a")["access_token"]
    with identity_session() as s:
        s.execute(update(AuthToken).where(AuthToken.token_hash == credentials.token_digest(tok))
                  .values(expires_at=now() - timedelta(seconds=1)))
    r = client.get("/api/v1/me", headers=_bearer(tok))
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert r.json()["error"]["message_key"] == "auth.token_invalid"


@pytest.mark.parametrize("header", [
    {"Authorization": "Bearer pra_not-a-real-token"},
    {"Authorization": "Basic Y2M6cHc="},
    {"Authorization": "Bearer "},
    {},
])
def test_missing_or_invalid_token_is_401(world, header):
    assert client.get("/api/v1/me", headers=header).status_code == 401
    assert client.get("/api/v1/patients", headers=header).status_code == 401


def test_refresh_rotates_tokens_and_revokes_previous_access_token(world):
    first = world.login("cc_a")
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"] and second["access_token"] != first["access_token"]
    assert client.get("/api/v1/me", headers=_bearer(first["access_token"])).status_code == 401
    assert client.get("/api/v1/me", headers=_bearer(second["access_token"])).status_code == 200


def test_refresh_token_reuse_revokes_the_whole_session(world):
    first = world.login("cc_a")
    second = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).json()
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401
    # The legitimate (newer) tokens of that session are revoked too.
    assert client.get("/api/v1/me", headers=_bearer(second["access_token"])).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401
    with identity_session() as s:
        sess = s.get(AuthSession, s.scalars(select(AuthToken.session_id).where(
            AuthToken.token_hash == credentials.token_digest(first["refresh_token"]))).one())
        assert sess.revoke_reason == "refresh_token_reuse"
    events = client.get("/api/v1/audit-events?action=auth.refresh_reuse_detected", headers=world.h("admin_a"))
    assert events.json()["total"] == 1


def test_access_token_cannot_be_used_as_refresh_token(world):
    tok = world.login("cc_a")
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tok["access_token"]}).status_code == 401


def test_logout_revokes_access_and_refresh_tokens(world):
    tok = world.login("cc_a")
    assert client.post("/api/v1/auth/logout", headers=_bearer(tok["access_token"])).status_code == 204
    assert client.get("/api/v1/me", headers=_bearer(tok["access_token"])).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]}).status_code == 401


def test_logout_all_ends_every_session(world):
    a = world.login("cc_a")["access_token"]
    b = _login(world.emails["cc_a"]).json()["access_token"]
    assert client.post("/api/v1/auth/logout-all", headers=_bearer(a)).status_code == 204
    assert client.get("/api/v1/me", headers=_bearer(b)).status_code == 401


def test_session_absolute_expiry(world):
    tok = world.login("cc_a")
    with identity_session() as s:
        s.execute(update(AuthSession).values(expires_at=now() - timedelta(seconds=1)))
    assert client.get("/api/v1/me", headers=_bearer(tok["access_token"])).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]}).status_code == 401


def test_admin_issued_password_reset_is_single_use_and_revokes_sessions(world):
    old = world.login("cc_a")["access_token"]
    issued = client.post(f"/api/v1/admin/users/{world.users['cc_a']}/password-reset", headers=world.h("admin_a"))
    assert issued.status_code == 200 and issued.json()["delivery"] == "out_of_band_not_sent"
    token = issued.json()["token"]
    new_pw = "Another-Synthetic-Passphrase-4"
    assert client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": new_pw}).status_code == 204
    assert client.get("/api/v1/me", headers=_bearer(old)).status_code == 401
    assert _login(world.emails["cc_a"]).status_code == 401
    assert _login(world.emails["cc_a"], new_pw).status_code == 200
    again = client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "Yet-Another-Pass-77x"})
    assert again.status_code == 400 and again.json()["error"]["message_key"] == "auth.one_time_token_invalid"


def test_password_reset_token_expires(world):
    token = client.post(f"/api/v1/admin/users/{world.users['cc_a']}/password-reset",
                        headers=world.h("admin_a")).json()["token"]
    with identity_session() as s:
        s.execute(update(OneTimeToken).values(expires_at=now() - timedelta(seconds=1)))
    r = client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "Expired-Token-Pass-1"})
    assert r.status_code == 400


def test_self_service_reset_request_does_not_reveal_accounts(world):
    known = client.post("/api/v1/auth/password-reset/request", json={"email": world.emails["cc_a"]})
    unknown = client.post("/api/v1/auth/password-reset/request", json={"email": "ghost@test.pulsereach.invalid"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()


def test_staff_activation_flow(world):
    r = client.post("/api/v1/admin/users", headers=world.h("admin_a"), json={
        "email": "New.Clinician@Test.Pulsereach.invalid", "full_name": "New Clinician", "role": "CLINICIAN"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["member"]["email"] == "new.clinician@test.pulsereach.invalid"
    assert body["member"]["password_set"] is False and body["activation"]["purpose"] == "activation"
    assert _login("new.clinician@test.pulsereach.invalid", "anything-at-all-1").status_code == 401
    pw = "Activated-Clinician-Pass-2"
    assert client.post("/api/v1/auth/password-reset/confirm",
                       json={"token": body["activation"]["token"], "new_password": pw}).status_code == 204
    tok = _login("new.clinician@test.pulsereach.invalid", pw)
    assert tok.status_code == 200 and tok.json()["role"] == "CLINICIAN"


def test_failed_logins_lock_the_account(world, monkeypatch):
    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 100)
    for _ in range(settings.login_max_failures):
        assert _login(world.emails["clin_a"], "wrong-password-xyz").status_code == 401
    locked = _login(world.emails["clin_a"])  # correct password, but locked
    assert locked.status_code == 429 and locked.json()["error"]["message_key"] == "auth.account_locked"
    with identity_session() as s:
        s.execute(update(UserAccount).values(locked_until=now() - timedelta(seconds=1)))
    assert _login(world.emails["clin_a"]).status_code == 200


def test_login_rate_limit(world, monkeypatch):
    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 3)
    codes = [_login(world.emails["phm_a"], "bad-password-000").status_code for _ in range(4)]
    assert codes[:3] == [401, 401, 401] and codes[3] == 429
    r = _login(world.emails["phm_a"])
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


def test_registration_is_non_enumerating_and_creates_unlinked_account(world):
    body = {"email": "new.patient@test.pulsereach.invalid", "password": "New-Patient-Passphrase-1",
            "full_name": "نورة (synthetic)", "preferred_language": "ar"}
    first = client.post("/api/v1/auth/register", json=body)
    dup = client.post("/api/v1/auth/register", json={**body, "password": "Different-Passphrase-2"})
    assert first.status_code == dup.status_code == 202
    assert first.json()["message_key"] == dup.json()["message_key"] == "auth.registration_accepted"
    assert first.json()["locale"] == "ar" and first.json()["direction"] == "rtl"
    tok = _login(body["email"], body["password"]).json()
    assert tok["role"] is None and tok["organization_id"] is None and tok["permissions"] == []
    me = client.get("/api/v1/me", headers=_bearer(tok["access_token"])).json()
    assert me["user"]["full_name"] == "نورة (synthetic)" and me["patient_linked"] is False
    # An unlinked account sees nothing.
    assert client.get("/api/v1/portal/summary", headers=_bearer(tok["access_token"])).status_code == 404
    assert client.get("/api/v1/patients", headers=_bearer(tok["access_token"])).status_code == 403


def test_registration_can_be_disabled(world, monkeypatch):
    monkeypatch.setattr(settings, "self_registration_enabled", False)
    r = client.post("/api/v1/auth/register", json={"email": "x@test.pulsereach.invalid",
                                                  "password": "Some-Passphrase-123", "full_name": "X"})
    assert r.status_code == 403


@pytest.mark.parametrize("password,key", [
    ("short", "auth.password_too_short"),
    ("aaaaaaaaaaaaaaaa", "auth.password_weak"),
    ("register.me-and-more", "auth.password_weak"),
])
def test_password_policy(world, password, key):
    r = client.post("/api/v1/auth/register", json={"email": "register.me@test.pulsereach.invalid",
                                                  "password": password, "full_name": "R"})
    assert r.status_code == 422 and r.json()["error"]["message_key"] == key


def test_change_password_keeps_current_session_and_revokes_others(world):
    current = world.login("cc_a")["access_token"]
    other = _login(world.emails["cc_a"]).json()["access_token"]
    bad = client.post("/api/v1/auth/password/change", headers=_bearer(current),
                      json={"current_password": "nope-nope-nope", "new_password": "Changed-Passphrase-77"})
    assert bad.status_code == 400
    ok = client.post("/api/v1/auth/password/change", headers=_bearer(current),
                     json={"current_password": PW, "new_password": "Changed-Passphrase-77"})
    assert ok.status_code == 204
    assert client.get("/api/v1/me", headers=_bearer(current)).status_code == 200
    assert client.get("/api/v1/me", headers=_bearer(other)).status_code == 401


def test_membership_deactivation_ends_access_in_that_organization(world):
    tok = world.login("phm_a")["access_token"]
    r = client.patch(f"/api/v1/admin/users/{world.users['phm_a']}", headers=world.h("admin_a"),
                     json={"membership_active": False})
    assert r.status_code == 200 and r.json()["membership_active"] is False
    assert client.get("/api/v1/me", headers=_bearer(tok)).status_code == 401


def test_switch_organization_requires_membership(world):
    tok = world.login("admin_a")["access_token"]
    r = client.post("/api/v1/auth/switch-organization", headers=_bearer(tok), json={"organization_id": world.org_b})
    assert r.status_code == 403
    # Grant a membership in B, then switching works and the old session ends.
    client.post("/api/v1/admin/users", headers=world.h("admin_b"), json={
        "email": "only.b@test.pulsereach.invalid", "full_name": "B", "role": "CLINICIAN"})
    from app.services.identity import directory

    with identity_session() as s:
        directory.add_membership(s, user_id=world.users["admin_a"], organization_id=world.org_b,
                                 role="SYSTEM_ADMIN", created_by=None)
    r = client.post("/api/v1/auth/switch-organization", headers=_bearer(tok), json={"organization_id": world.org_b})
    assert r.status_code == 200 and r.json()["organization_id"] == world.org_b
    assert client.get("/api/v1/me", headers=_bearer(tok)).status_code == 401


def test_secrets_never_logged(world, caplog):
    caplog.set_level(logging.DEBUG)
    tok = world.login("cc_a")
    _login(world.emails["cc_a"], "wrong-password-logged?")
    client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    for secret in (PW, tok["access_token"], tok["refresh_token"], "wrong-password-logged?"):
        assert secret not in caplog.text


def test_legacy_mode_has_no_auth_endpoints(users_mode, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "legacy")
    assert client.post(LOGIN, json={"email": "a@b.cd", "password": "x"}).status_code == 404
    assert client.get("/api/v1/portal/summary").status_code == 404
