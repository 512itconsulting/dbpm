from __future__ import annotations

from .environment import EnvironmentPolicy
from .errors import DependencyError
from .planner import create_plan
from .provenance import resolve_provenance
from .source import PackageSource


def create_multi_package_plan(
    *,
    mode: str,
    source: PackageSource,
    dependency_sources: list[PackageSource],
    environment: EnvironmentPolicy,
    installed_states: dict[str, dict[str, str] | None] | None = None,
    reverse_dependencies: dict[str, list[str]] | None = None,
    allow_destructive: bool = False,
    approve: bool = False,
) -> dict[str, object]:
    installed_states = installed_states or {}
    reverse_dependencies = reverse_dependencies or {}
    ordered_sources, satisfied = _resolve_dependency_order(source, dependency_sources, installed_states)

    package_plans: list[dict[str, object]] = []
    for item in ordered_sources:
        app_name = item.manifest.application_name
        state = installed_states.get(app_name)
        item_mode = mode if item is source else "install"
        package_plans.append(
            create_plan(
                mode=item_mode,
                source=item,
                provenance=resolve_provenance(item),
                environment=environment,
                installed_state=state,
                reverse_dependencies=reverse_dependencies.get(app_name, []),
                allow_destructive=allow_destructive if item is source else False,
                approve=approve,
            )
        )

    return {
        "schema_version": "dbpm.multi-plan.v0",
        "mode": mode,
        "package": {
            "name": source.manifest.name,
            "application_name": source.manifest.application_name,
            "version": source.manifest.version,
        },
        "execution_order": [
            plan["package"]["application_name"]
            for plan in package_plans
            if isinstance(plan.get("package"), dict)
        ],
        "satisfied_dependencies": satisfied,
        "packages": package_plans,
    }


def _resolve_dependency_order(
    source: PackageSource,
    dependency_sources: list[PackageSource],
    installed_states: dict[str, dict[str, str] | None],
) -> tuple[list[PackageSource], list[dict[str, object]]]:
    available = {item.manifest.application_name: item for item in [source, *dependency_sources]}
    ordered: list[PackageSource] = []
    satisfied: list[dict[str, object]] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    satisfied_apps: set[str] = set()

    def visit(item: PackageSource) -> None:
        app_name = item.manifest.application_name
        if app_name in visited:
            return
        if app_name in visiting:
            raise DependencyError(f"Dependency cycle detected at {app_name}")

        visiting.add(app_name)
        for dependency in item.manifest.dependencies:
            dep_app = _application_name(dependency.name)
            dep_source = available.get(dep_app)
            dep_state = installed_states.get(dep_app)
            _assert_supported_constraint(dependency.version)
            if dep_state is not None and _state_satisfies_dependency(dep_state, dependency.version):
                if dep_app not in satisfied_apps:
                    satisfied.append(
                        {
                            "application_name": dep_app,
                            "version": dependency.version,
                            "installed_state": dep_state,
                        }
                    )
                    satisfied_apps.add(dep_app)
                continue
            if dep_source is None:
                raise DependencyError(
                    f"Missing dependency source for {item.manifest.application_name}: "
                    f"{dep_app} {dependency.version}"
                )
            if dep_source.manifest.version != dependency.version:
                raise DependencyError(
                    f"Dependency source {dep_app} version {dep_source.manifest.version} "
                    f"does not satisfy required version {dependency.version}"
                )
            visit(dep_source)
        visiting.remove(app_name)
        visited.add(app_name)
        ordered.append(item)

    visit(source)
    return ordered, satisfied


def _state_satisfies_dependency(state: dict[str, str], version: str) -> bool:
    return state.get("deploy_status") == "C" and state.get("version") == version


def _assert_supported_constraint(version: str) -> None:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise DependencyError(f"Unsupported dependency version constraint: {version}")


def _application_name(name: str) -> str:
    return name.replace("-", "_").upper()
