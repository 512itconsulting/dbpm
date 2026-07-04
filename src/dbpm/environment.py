from __future__ import annotations

from dataclasses import dataclass

from .errors import PolicyError


LOCKED_VALUES = {
    "locked": True,
    "true": True,
    "y": True,
    "yes": True,
    "1": True,
    "unlocked": False,
    "false": False,
    "n": False,
    "no": False,
    "0": False,
}


@dataclass(frozen=True)
class DeploymentPolicy:
    deployment_locked: bool
    source: str = "default"
    deploy_environment: str | None = None

    def evaluate(
        self,
        mode: str,
        *,
        dirty: bool | None,
        allow_destructive: bool = False,
        approve: bool = False,
    ) -> dict[str, object]:
        blocked: list[str] = []
        approvals: list[str] = []
        warnings: list[str] = []

        if self.deployment_locked:
            if mode == "reinstall":
                blocked.append("`reinstall` is blocked when DEPLOY_LOCKED=Y")
            elif mode == "resume" and not approve:
                approvals.append("`resume` requires approval when DEPLOY_LOCKED=Y")

            if dirty is True:
                blocked.append("Dirty source/artifact is blocked when DEPLOY_LOCKED=Y")
        else:
            if dirty is True:
                warnings.append("Dirty source/artifact will be deployed")

        if mode == "reinstall" and not allow_destructive:
            approvals.append("`reinstall` requires --allow-destructive")

        return {
            "policy_context": self.as_dict(),
            "result": "blocked" if blocked else "requires-approval" if approvals else "allowed",
            "blocked": blocked,
            "required_approvals": approvals,
            "warnings": warnings,
        }

    def enforce(self, evaluation: dict[str, object]) -> None:
        if evaluation["result"] != "allowed":
            reasons = [*evaluation["blocked"], *evaluation["required_approvals"]]  # type: ignore[index]
            raise PolicyError("; ".join(str(reason) for reason in reasons))

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "deployment_locked": self.deployment_locked,
            "source": self.source,
        }
        if self.deploy_environment is not None:
            result["deploy_environment"] = self.deploy_environment
        return result


def resolve_deployment_policy(value: str | None, *, source: str = "default") -> DeploymentPolicy:
    if value is None:
        return DeploymentPolicy(deployment_locked=False, source=source)
    normalized = value.strip().lower()
    if normalized not in LOCKED_VALUES:
        raise PolicyError(f"Unknown deployment policy: {value}")
    return DeploymentPolicy(deployment_locked=LOCKED_VALUES[normalized], source=source)


def policy_from_core_values(
    *,
    deploy_locked: str | None,
    deploy_environment: str | None = None,
) -> DeploymentPolicy:
    if deploy_locked is None or not deploy_locked.strip():
        raise PolicyError("CORE/DEPLOY_LOCKED is required")
    normalized = deploy_locked.strip().upper()
    if normalized not in {"Y", "N"}:
        raise PolicyError("CORE/DEPLOY_LOCKED must be Y or N")
    return DeploymentPolicy(
        deployment_locked=normalized == "Y",
        source="core-dictionary",
        deploy_environment=deploy_environment,
    )
