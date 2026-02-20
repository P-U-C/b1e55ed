"""Role-based permissions (P1)."""

from engine.core.permissions import Permission, check_permission, get_role_permissions, has_permission


def test_operator_has_all_permissions() -> None:
    perms = get_role_permissions("operator")
    assert Permission.BRAIN_CYCLE in perms
    assert Permission.KILL_SWITCH in perms
    assert Permission.KARMA_SETTLE in perms
    assert Permission.SIGNAL_SUBMIT in perms
    assert Permission.CONFIG_WRITE in perms


def test_agent_limited_permissions() -> None:
    assert has_permission("agent", Permission.SIGNAL_SUBMIT)
    assert has_permission("agent", Permission.BRAIN_STATUS)
    assert has_permission("agent", Permission.PRODUCER_REGISTER)
    assert not has_permission("agent", Permission.BRAIN_CYCLE)
    assert not has_permission("agent", Permission.KILL_SWITCH)
    assert not has_permission("agent", Permission.KARMA_SETTLE)
    assert not has_permission("agent", Permission.CONFIG_WRITE)


def test_curator_can_signal_only() -> None:
    assert has_permission("curator", Permission.SIGNAL_SUBMIT)
    assert not has_permission("curator", Permission.PRODUCER_REGISTER)
    assert not has_permission("curator", Permission.KILL_SWITCH)


def test_tester_most_restricted() -> None:
    assert has_permission("tester", Permission.SIGNAL_SUBMIT)
    assert has_permission("tester", Permission.BRAIN_STATUS)
    assert not has_permission("tester", Permission.BRAIN_CYCLE)
    assert not has_permission("tester", Permission.KARMA_SETTLE)
    assert not has_permission("tester", Permission.PRODUCER_REGISTER)


def test_unknown_role_denied() -> None:
    result = check_permission("hacker", Permission.SIGNAL_SUBMIT)
    assert not result.allowed
    assert "Unknown role" in result.reason


def test_check_returns_reason() -> None:
    result = check_permission("tester", Permission.KILL_SWITCH)
    assert not result.allowed
    assert "lacks permission" in result.reason
