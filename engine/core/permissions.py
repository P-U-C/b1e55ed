"""engine.core.permissions

Role-based access control (P1).

Permission matrix:
| Role     | Signal | Brain | Kill Switch | Settle Karma | Register Producers |
|----------|--------|-------|-------------|--------------|-------------------|
| operator | yes    | yes   | yes         | yes          | yes               |
| agent    | yes    | no    | no          | no           | own only          |
| curator  | yes    | no    | no          | no           | no                |
| tester   | limited| no    | no          | no           | no                |

Tester limits: max 10 signals/day, no live execution signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    OPERATOR = "operator"
    AGENT = "agent"
    CURATOR = "curator"
    TESTER = "tester"


class Permission(StrEnum):
    SIGNAL_SUBMIT = "signal.submit"
    BRAIN_CYCLE = "brain.cycle"
    BRAIN_STATUS = "brain.status"
    KILL_SWITCH = "kill_switch"
    KARMA_SETTLE = "karma.settle"
    KARMA_VIEW = "karma.view"
    PRODUCER_REGISTER = "producer.register"
    PRODUCER_MANAGE_ALL = "producer.manage_all"
    CONTRIBUTOR_MANAGE = "contributor.manage"
    EVENTS_READ = "events.read"
    CONFIG_READ = "config.read"
    CONFIG_WRITE = "config.write"


# Permission matrix
_ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.OPERATOR: set(Permission),  # All permissions
    Role.AGENT: {
        Permission.SIGNAL_SUBMIT,
        Permission.BRAIN_STATUS,
        Permission.KARMA_VIEW,
        Permission.PRODUCER_REGISTER,
        Permission.EVENTS_READ,
        Permission.CONFIG_READ,
    },
    Role.CURATOR: {
        Permission.SIGNAL_SUBMIT,
        Permission.BRAIN_STATUS,
        Permission.KARMA_VIEW,
        Permission.EVENTS_READ,
    },
    Role.TESTER: {
        Permission.SIGNAL_SUBMIT,
        Permission.BRAIN_STATUS,
        Permission.EVENTS_READ,
    },
}


@dataclass(frozen=True, slots=True)
class PermissionCheckResult:
    allowed: bool
    reason: str = ""


def check_permission(role: str, permission: Permission) -> PermissionCheckResult:
    """Check if a role has a specific permission."""
    try:
        r = Role(role)
    except ValueError:
        return PermissionCheckResult(allowed=False, reason=f"Unknown role: {role}")

    perms = _ROLE_PERMISSIONS.get(r, set())
    if permission in perms:
        return PermissionCheckResult(allowed=True)

    return PermissionCheckResult(
        allowed=False,
        reason=f"Role '{role}' lacks permission '{permission}'",
    )


def get_role_permissions(role: str) -> set[Permission]:
    """Return all permissions for a role."""
    try:
        r = Role(role)
    except ValueError:
        return set()
    return _ROLE_PERMISSIONS.get(r, set())


def has_permission(role: str, permission: Permission) -> bool:
    """Quick boolean check."""
    return check_permission(role, permission).allowed
