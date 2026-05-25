from dbpm.environment import resolve_environment


def test_reinstall_blocked_in_production_even_with_destructive_flag():
    policy = resolve_environment("prod")
    result = policy.evaluate(
        "reinstall",
        dirty=False,
        allow_destructive=True,
        approve=True,
    )

    assert result["result"] == "blocked"
    assert "`reinstall` is blocked in production" in result["blocked"]


def test_dirty_source_requires_approval_in_test():
    policy = resolve_environment("test")
    result = policy.evaluate("install", dirty=True)

    assert result["result"] == "requires-approval"
    assert "Dirty source/artifact requires approval in test" in result["required_approvals"]


def test_dirty_source_blocked_in_staging():
    policy = resolve_environment("staging")
    result = policy.evaluate("install", dirty=True, approve=True)

    assert result["result"] == "blocked"
    assert "Dirty source/artifact is blocked in staging" in result["blocked"]


def test_reinstall_allowed_in_development_with_destructive_flag():
    policy = resolve_environment("development")
    result = policy.evaluate("reinstall", dirty=False, allow_destructive=True)

    assert result["result"] == "allowed"
