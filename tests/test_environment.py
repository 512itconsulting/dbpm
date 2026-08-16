import pytest

from dbpm.environment import policy_from_core_values, resolve_deployment_policy
from dbpm.errors import PolicyError


def test_reinstall_blocked_when_deploy_locked_even_with_destructive_flag():
    policy = policy_from_core_values(deploy_locked="Y")
    result = policy.evaluate(
        "reinstall",
        dirty=False,
        allow_destructive=True,
        approve=True,
    )

    assert result["result"] == "blocked"
    assert "`reinstall` is blocked when DEPLOY_LOCKED=Y" in result["blocked"]


def test_dirty_source_blocked_when_deploy_locked():
    policy = policy_from_core_values(deploy_locked="Y")
    result = policy.evaluate("install", dirty=True, approve=True)

    assert result["result"] == "blocked"
    assert "Dirty source/artifact is blocked when DEPLOY_LOCKED=Y" in result["blocked"]


def test_resume_requires_approval_when_deploy_locked():
    policy = policy_from_core_values(deploy_locked="Y")
    result = policy.evaluate("resume", dirty=False)

    assert result["result"] == "requires-approval"
    assert "`resume` requires approval when DEPLOY_LOCKED=Y" in result["required_approvals"]


def test_reinstall_allowed_when_unlocked_with_destructive_flag():
    policy = policy_from_core_values(deploy_locked="N")
    result = policy.evaluate("reinstall", dirty=False, allow_destructive=True)

    assert result["result"] == "allowed"


def test_cli_policy_locked_alias():
    policy = resolve_deployment_policy("locked", source="cli-policy")

    assert policy.deployment_locked is True
    assert policy.as_dict() == {"deployment_locked": True, "source": "cli-policy"}


def test_core_policy_missing_deploy_locked_fails():
    with pytest.raises(PolicyError, match="CORE/DEPLOY_LOCKED is required"):
        policy_from_core_values(deploy_locked=None)


def test_core_policy_invalid_deploy_locked_fails():
    with pytest.raises(PolicyError, match="CORE/DEPLOY_LOCKED must be Y or N"):
        policy_from_core_values(deploy_locked="MAYBE")


def test_lifecycle_capabilities_are_independent_and_fail_closed():
    policy = policy_from_core_values(
        deploy_locked="N",
        capabilities={"DBPM_ALLOW_GRAPH_RESET": "Y"},
    )

    graph = policy.evaluate(
        "reinstall", dirty=False, allow_destructive=True,
        required_capabilities=("DBPM_ALLOW_GRAPH_RESET",),
    )
    environment = policy.evaluate(
        "uninstall", dirty=False, allow_destructive=True,
        required_capabilities=("DBPM_ALLOW_ENVIRONMENT_RESET",),
    )

    assert graph["result"] == "allowed"
    assert environment["result"] == "blocked"
    assert "DBPM_ALLOW_ENVIRONMENT_RESET" in environment["blocked"][0]
