from __future__ import annotations

from dataclasses import dataclass

from .errors import PolicyError


ENV_CLASSES = {"development", "test", "staging", "production"}

ALIASES = {
    "dev": "development",
    "development": "development",
    "test": "test",
    "qa": "test",
    "stage": "staging",
    "staging": "staging",
    "prod": "production",
    "production": "production",
}

MODE_POLICY = {
    "bootstrap-core": {
        "development": "allow",
        "test": "allow",
        "staging": "require-approval",
        "production": "require-approval",
    },
    "install": {
        "development": "allow",
        "test": "allow",
        "staging": "allow",
        "production": "allow",
    },
    "upgrade": {
        "development": "allow",
        "test": "allow",
        "staging": "allow",
        "production": "allow",
    },
    "repair": {
        "development": "allow",
        "test": "allow",
        "staging": "require-approval",
        "production": "require-approval",
    },
    "reinstall": {
        "development": "allow",
        "test": "require-approval",
        "staging": "block",
        "production": "block",
    },
}


@dataclass(frozen=True)
class EnvironmentPolicy:
    name: str
    env_class: str
    source: str = "cli"

    def evaluate(
        self,
        mode: str,
        *,
        dirty: bool | None,
        allow_destructive: bool = False,
        approve: bool = False,
    ) -> dict[str, object]:
        mode_result = MODE_POLICY.get(mode, {}).get(self.env_class, "block")
        blocked: list[str] = []
        approvals: list[str] = []
        warnings: list[str] = []

        if mode_result == "block":
            blocked.append(f"`{mode}` is blocked in {self.env_class}")
        elif mode_result == "require-approval" and not approve:
            approvals.append(f"`{mode}` requires approval in {self.env_class}")

        if mode == "reinstall" and not allow_destructive:
            approvals.append("`reinstall` requires --allow-destructive")

        if dirty is True:
            if self.env_class in {"staging", "production"}:
                blocked.append(f"Dirty source/artifact is blocked in {self.env_class}")
            elif self.env_class == "test" and not approve:
                approvals.append("Dirty source/artifact requires approval in test")
            else:
                warnings.append("Dirty source/artifact will be deployed")

        return {
            "environment": self.as_dict(),
            "result": "blocked" if blocked else "requires-approval" if approvals else "allowed",
            "blocked": blocked,
            "required_approvals": approvals,
            "warnings": warnings,
        }

    def enforce(self, evaluation: dict[str, object]) -> None:
        if evaluation["result"] != "allowed":
            reasons = [*evaluation["blocked"], *evaluation["required_approvals"]]  # type: ignore[index]
            raise PolicyError("; ".join(str(reason) for reason in reasons))

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "class": self.env_class, "source": self.source}


def resolve_environment(name: str | None) -> EnvironmentPolicy:
    raw = name or "development"
    env_class = ALIASES.get(raw.lower())
    if env_class is None:
        env_class = raw.lower()
    if env_class not in ENV_CLASSES:
        raise PolicyError(f"Unknown environment: {raw}")
    return EnvironmentPolicy(name=raw, env_class=env_class)
