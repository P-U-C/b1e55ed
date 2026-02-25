"""tests/e2e/test_contributor_flow.py

End-to-end tests for the full contributor lifecycle.
Uses real DB + real ContributorRegistry; mocks only external calls (GitHub, EAS).

Critical regression targets
----------------------------
* Registration must be fail-open: a broken / absent publisher MUST NOT block
  contributor storage.
* github_publisher is best-effort: call is captured, failure is swallowed.
"""

from __future__ import annotations

import pytest

from engine.core.contributors import ContributorRegistry
from engine.core.database import Database
from engine.core.scoring import ContributorScoring

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "brain.db")
    yield d
    d.close()


@pytest.fixture()
def reg(db):
    """Registry without any external integrations."""
    return ContributorRegistry(db)


# ---------------------------------------------------------------------------
# 1. Register → verify stored
# ---------------------------------------------------------------------------


def test_register_stores_in_db(db):
    reg = ContributorRegistry(db)
    c = reg.register(node_id="node-1", name="Alice", role="agent", metadata={"foo": "bar"})

    assert c.id is not None
    assert c.node_id == "node-1"
    assert c.name == "Alice"
    assert c.role == "agent"
    assert c.metadata.get("foo") == "bar"

    # Also verify it's retrievable via get()
    fetched = reg.get(c.id)
    assert fetched is not None
    assert fetched.id == c.id
    assert fetched.name == "Alice"


# ---------------------------------------------------------------------------
# 2. github_publisher is called with correct arguments
# ---------------------------------------------------------------------------


def test_github_publisher_called(db):
    calls = []

    def mock_publisher(**kwargs):
        calls.append(kwargs)
        return {"html_url": "https://github.com/test/123"}

    reg = ContributorRegistry(db, github_publisher=mock_publisher)
    c = reg.register(node_id="node-pub", name="Bob", role="agent")

    # Publisher must have been invoked exactly once
    assert len(calls) == 1, "github_publisher should be called once on registration"
    call = calls[0]
    # Check expected kwargs are present
    assert call.get("name") == "Bob"
    assert call.get("node_id") == "node-pub"
    assert call.get("role") == "agent"
    assert call.get("contributor_id") == c.id

    # Publish result stored in metadata
    assert c.metadata.get("publish", {}).get("github", {}).get("html_url") == "https://github.com/test/123"


# ---------------------------------------------------------------------------
# 3. Retrieve via reg.get(id) → metadata matches
# ---------------------------------------------------------------------------


def test_get_by_id_metadata_round_trip(db):
    reg = ContributorRegistry(db)
    meta = {"tier": "gold", "region": "us-east", "nested": {"level": 2}}
    c = reg.register(node_id="node-meta", name="Carol", role="tester", metadata=meta)

    fetched = reg.get(c.id)
    assert fetched is not None
    assert fetched.metadata["tier"] == "gold"
    assert fetched.metadata["region"] == "us-east"
    assert fetched.metadata["nested"]["level"] == 2


# ---------------------------------------------------------------------------
# 4. Compute contributor score → verify structure
# ---------------------------------------------------------------------------


def test_contributor_score_structure(db):
    reg = ContributorRegistry(db)
    c = reg.register(node_id="node-score", name="Dave", role="agent")

    scoring = ContributorScoring(db)
    score = scoring.compute_score(c.id)

    assert score.contributor_id == c.id
    assert isinstance(score.signals_submitted, int)
    assert isinstance(score.signals_accepted, int)
    assert isinstance(score.hit_rate, float)
    assert isinstance(score.score, float)
    assert 0.0 <= score.score <= 100.0
    assert isinstance(score.brier_score, float)
    assert isinstance(score.streak, int)


# ---------------------------------------------------------------------------
# 5. Deregister → gone from DB
# ---------------------------------------------------------------------------


def test_deregister_removes_contributor(db):
    reg = ContributorRegistry(db)
    c = reg.register(node_id="node-del", name="Eve", role="agent")

    assert reg.get(c.id) is not None, "Must exist before deregister"
    removed = reg.deregister(c.id)
    assert removed is True, "deregister should return True for existing contributor"
    assert reg.get(c.id) is None, "Must be gone after deregister"


def test_deregister_nonexistent_returns_false(db):
    reg = ContributorRegistry(db)
    assert reg.deregister("does-not-exist") is False


# ---------------------------------------------------------------------------
# 6. Duplicate registration → raises ValueError
# ---------------------------------------------------------------------------


def test_duplicate_registration_raises(db):
    reg = ContributorRegistry(db)
    reg.register(node_id="node-dup", name="Frank", role="agent")

    with pytest.raises(ValueError, match="contributor.duplicate_node"):
        reg.register(node_id="node-dup", name="Frank-2", role="agent")


# ---------------------------------------------------------------------------
# 7. CRITICAL: Register without publisher configured → contributor STILL registered
# ---------------------------------------------------------------------------


def test_register_without_publisher_succeeds(db):
    """Fail-open: no publisher configured → registration must not fail."""
    reg = ContributorRegistry(db, github_publisher=None)
    c = reg.register(node_id="node-nopub", name="Grace", role="agent")

    assert c.id is not None
    fetched = reg.get(c.id)
    assert fetched is not None
    assert fetched.node_id == "node-nopub"


# ---------------------------------------------------------------------------
# 8. CRITICAL: Register with broken publisher → contributor STILL registered
# ---------------------------------------------------------------------------


def test_register_with_broken_publisher_still_stores(db):
    """Fail-open: publisher raises → registration must succeed anyway."""

    def broken_publisher(**kwargs):
        raise RuntimeError("GitHub API is down!")

    reg = ContributorRegistry(db, github_publisher=broken_publisher)
    # Must NOT raise
    c = reg.register(node_id="node-broken", name="Henry", role="agent")

    assert c.id is not None
    # Contributor must be persisted despite publisher failure
    fetched = reg.get(c.id)
    assert fetched is not None, "Contributor must be stored even when publisher raises"
    assert fetched.node_id == "node-broken"


# ---------------------------------------------------------------------------
# 9. Publisher returning None → contributor still registered cleanly
# ---------------------------------------------------------------------------


def test_register_with_publisher_returning_none(db):
    """Publisher that returns None (falsy) should not pollute metadata."""

    def null_publisher(**kwargs):
        return None

    reg = ContributorRegistry(db, github_publisher=null_publisher)
    c = reg.register(node_id="node-nullpub", name="Ivy", role="agent")
    assert c.id is not None
    fetched = reg.get(c.id)
    assert fetched is not None
    # publish.github should NOT be set (falsy return)
    assert fetched.metadata.get("publish", {}).get("github") is None


# ---------------------------------------------------------------------------
# 10. list_all returns registered contributors
# ---------------------------------------------------------------------------


def test_list_all_returns_contributors(db):
    reg = ContributorRegistry(db)
    ids = set()
    for i in range(3):
        c = reg.register(node_id=f"node-list-{i}", name=f"Agent-{i}", role="agent")
        ids.add(c.id)

    all_contributors = reg.list_all()
    stored_ids = {c.id for c in all_contributors}
    assert ids.issubset(stored_ids)
