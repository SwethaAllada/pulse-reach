import pytest

from app.db.runtime_role import DATA_SCHEMAS, ensure_runtime_role, runtime_grants

OWNER = "postgresql+psycopg://pulsereach_owner:owner-password-0123456789abcdef@/pulsereach?host=/cloudsql/x"


def _runtime(user="pulsereach_app", pw="0123456789abcdef0123456789abcdef", db="pulsereach"):
    return f"postgresql+psycopg://{user}:{pw}@/{db}?host=/cloudsql/x"


@pytest.mark.parametrize("url", [
    _runtime(user="pulsereach_owner"),        # same as the owner
    _runtime(user="Bad-Role"),                # not a plain identifier
    _runtime(pw="short"),                     # weak password
    _runtime(db="other"),                     # different database
])
def test_rejects_unsafe_runtime_urls_before_connecting(url):
    with pytest.raises(SystemExit):
        ensure_runtime_role(OWNER, url)


def test_grants_are_data_only_on_every_app_schema():
    text = " ".join(repr(s) for s in runtime_grants("pulsereach_owner", "pulsereach_app", "pulsereach"))
    assert set(DATA_SCHEMAS) == {"official", "clinical", "synthetic", "identity", "engagement", "population"}
    for schema in DATA_SCHEMAS:
        assert f"Identifier('{schema}')" in text
    for forbidden in ("TRUNCATE", "CREATE ON", "ALL PRIVILEGES", "SUPERUSER", "CREATEROLE", "REFERENCES", "TRIGGER"):
        assert forbidden not in text
