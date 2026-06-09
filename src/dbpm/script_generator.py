from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from .errors import DbpmError
from .manifest import MANIFEST_NAMES, parse_manifest
from .resolver import parse_version


DEFAULT_INSTALL_OUTPUT = "Deployment_Manifests/deploy.sql"
DEFAULT_UPGRADE_POINTER_OUTPUT = "Deployment_Manifests/update.sql"
DEFAULT_RELEASE_UPGRADE_OUTPUT = "Deployment_Manifests/releases/{version}/update.sql"

OBJECT_DIRECTORIES = (
    "Sequences",
    "Tables",
    "Types",
    "Views",
    "Functions",
    "Procedures",
    "Packages",
    "Metadata",
)

GROUP_LABELS = {
    "Sequences": "Sequences",
    "Tables": "Tables",
    "Types:spec": "Type Specifications",
    "Types": "Types",
    "Types:body": "Type Bodies",
    "Views": "Views",
    "Functions": "Functions",
    "Procedures": "Procedures",
    "Packages:spec": "Package Specifications",
    "Packages:body": "Package Bodies",
    "Metadata": "Metadata",
}

OBJECT_CONSTANTS = {
    "Sequences": "pkg_application.c_object_type_sequence",
    "Tables": "pkg_application.c_object_type_table",
    "Types:spec": "pkg_application.c_object_type_type",
    "Types": "pkg_application.c_object_type_type",
    "Types:body": "pkg_application.c_object_type_type",
    "Views": "pkg_application.c_object_type_view",
    "Functions": "pkg_application.c_object_type_function",
    "Procedures": "pkg_application.c_object_type_procedure",
    "Packages:spec": "pkg_application.c_object_type_package",
    "Packages:body": "pkg_application.c_object_type_package_body",
}

LIFECYCLE_RE = re.compile(
    r"^(?P<directory>[^/]+)/(?P<object>.+)\."
    r"(?P<action>alter|recreate|drop)\."
    r"(?P<version>\d+\.\d+\.\d+)\.sql$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ObjectFile:
    path: str
    directory: str
    name: str
    group: str
    object_constant: str | None


@dataclass(frozen=True)
class LifecycleFile:
    path: str
    directory: str
    name: str
    action: str
    version: str


@dataclass(frozen=True)
class GenerationOptions:
    root: Path      # package root — where dbpm.yaml lives and outputs are written
    git_root: Path  # git repository root — used for all git commands
    from_ref: str | None
    to_ref: str
    version: str
    application_name: str
    install_output: str
    release_upgrade_output: str | None
    upgrade_pointer_output: str | None
    deployment_type: str | None
    check: bool = False


@dataclass(frozen=True)
class GenerationResult:
    outputs: tuple[Path, ...]
    warnings: tuple[str, ...]
    changed: tuple[Path, ...]


def resolve_generation_options(
    root: Path,
    *,
    from_ref: str | None = None,
    to_ref: str = "HEAD",
    version: str | None = None,
    application_name: str | None = None,
    install_output: str | None = None,
    release_upgrade_output: str | None = None,
    upgrade_pointer_output: str | None = None,
    deployment_type: str | None = None,
    check: bool = False,
) -> GenerationOptions:
    package_root = root.resolve()
    git_root = Path(_git(package_root, "rev-parse", "--show-toplevel").strip()).resolve()
    if from_ref is not None:
        _git(git_root, "rev-parse", "--verify", f"{from_ref}^{{commit}}")
    _git(git_root, "rev-parse", "--verify", f"{to_ref}^{{commit}}")

    subpath = package_root.relative_to(git_root)
    manifest, raw_manifest = _manifest_at_ref(git_root, subpath, to_ref)
    previous_manifest = None
    if from_ref is not None:
        previous_manifest, _ = _manifest_at_ref(git_root, subpath, from_ref)
    resolved_version = version or (manifest.version if manifest else None)
    if resolved_version is None:
        raise DbpmError("Script generation requires --version when dbpm.yaml is absent")
    try:
        parse_version(resolved_version)
    except Exception as exc:
        raise DbpmError(f"Invalid target version for script generation: {resolved_version}") from exc

    resolved_application = application_name or (
        manifest.application_name if manifest else _application_name(package_root.name)
    )
    resolved_application = _application_name(resolved_application)
    if resolved_application == "CORE":
        raise DbpmError(
            "Core script generation is not supported; Core requires bootstrap-aware lifecycle SQL"
        )

    generation = raw_manifest.get("generation", {}) if isinstance(raw_manifest, dict) else {}
    if not isinstance(generation, dict):
        generation = {}
    resolved_install = (
        install_output
        or (manifest.scripts.install if manifest else None)
        or DEFAULT_INSTALL_OUTPUT
    )
    if from_ref is None:
        if deployment_type is not None:
            raise DbpmError("--deployment-type requires --from")
        if release_upgrade_output is not None:
            raise DbpmError("--release-upgrade-output requires --from")
        if upgrade_pointer_output is not None:
            raise DbpmError("--upgrade-pointer-output requires --from")
        return GenerationOptions(
            root=package_root,
            git_root=git_root,
            from_ref=None,
            to_ref=to_ref,
            version=resolved_version,
            application_name=resolved_application,
            install_output=_normalize_output(resolved_install),
            release_upgrade_output=None,
            upgrade_pointer_output=None,
            deployment_type=None,
            check=check,
        )

    resolved_pointer = (
        upgrade_pointer_output
        or (manifest.scripts.upgrade if manifest else None)
        or DEFAULT_UPGRADE_POINTER_OUTPUT
    )
    resolved_release = (
        release_upgrade_output
        or _optional_string(generation.get("release_upgrade_output"))
        or DEFAULT_RELEASE_UPGRADE_OUTPUT.format(version=resolved_version)
    )
    resolved_release = resolved_release.replace("<version>", resolved_version).replace(
        "{version}", resolved_version
    )

    outputs = {
        _normalize_output(resolved_install),
        _normalize_output(resolved_release),
        _normalize_output(resolved_pointer),
    }
    if len(outputs) != 3:
        raise DbpmError("Install, release upgrade, and upgrade pointer outputs must be distinct")

    return GenerationOptions(
        root=package_root,
        git_root=git_root,
        from_ref=from_ref,
        to_ref=to_ref,
        version=resolved_version,
        application_name=resolved_application,
        install_output=_normalize_output(resolved_install),
        release_upgrade_output=_normalize_output(resolved_release),
        upgrade_pointer_output=_normalize_output(resolved_pointer),
        deployment_type=_deployment_type(
            resolved_version,
            deployment_type,
            previous_manifest.version if previous_manifest else _version_from_ref(from_ref),
        ),
        check=check,
    )


def generate_scripts(options: GenerationOptions) -> GenerationResult:
    subpath = options.root.relative_to(options.git_root)
    to_paths = _tree_paths(options.git_root, subpath, options.to_ref)
    objects = {
        item.path: item
        for item in (_object_file(path) for path in to_paths)
        if item is not None
    }
    object_order = _compute_object_order(objects, options.git_root, subpath, options.to_ref)
    install_sql = _render_install(options, objects.values(), object_order=object_order)
    rendered = {options.install_output: install_sql}

    warnings: list[str] = []
    if options.from_ref is not None:
        assert options.release_upgrade_output is not None
        assert options.upgrade_pointer_output is not None
        assert options.deployment_type is not None
        changed = _diff_paths(options.git_root, subpath, options.from_ref, options.to_ref)
        update_sql, warnings = _render_update(
            options,
            objects,
            _changed_lifecycle(to_paths, changed, options),
            changed,
            object_order=object_order,
        )
        pointer_sql = _render_pointer(options)
        rendered[options.release_upgrade_output] = update_sql
        rendered[options.upgrade_pointer_output] = pointer_sql

    return _write_generated_outputs(options, rendered, warnings)


def _changed_lifecycle(
    to_paths: Iterable[str],
    changed: dict[str, str],
    options: GenerationOptions,
) -> list[LifecycleFile]:
    lifecycle = []
    for path in to_paths:
        item = _lifecycle_file(path)
        if item is not None and path in changed:
            lifecycle.append(item)
    for item in lifecycle:
        if item.version != options.version:
            raise DbpmError(
                f"Lifecycle script {item.path} targets {item.version}, expected {options.version}"
            )
    return lifecycle


def _write_generated_outputs(
    options: GenerationOptions,
    rendered: dict[str, str],
    warnings: list[str],
) -> GenerationResult:
    changed_outputs: list[Path] = []
    outputs: list[Path] = []
    for relative_path, content in rendered.items():
        output = options.root / relative_path
        outputs.append(output)
        current = output.read_text(encoding="utf-8") if output.exists() else None
        if current == content:
            continue
        changed_outputs.append(output)
        if not options.check:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content, encoding="utf-8")

    if options.check and changed_outputs:
        paths = ", ".join(str(path.relative_to(options.root)) for path in changed_outputs)
        raise DbpmError(f"Generated scripts are stale or missing: {paths}")

    return GenerationResult(
        outputs=tuple(outputs),
        warnings=tuple(warnings),
        changed=tuple(changed_outputs),
    )


def _render_install(
    options: GenerationOptions,
    objects: Iterable[ObjectFile],
    *,
    object_order: dict[str, int] | None = None,
) -> str:
    ordered = sorted(objects, key=_object_sort_key)
    registrations = [item for item in ordered if item.object_constant]
    sections = _render_object_sections(
        options.install_output,
        ordered,
        include_metadata=True,
        object_order=object_order,
    )
    return _render_deployment(
        application_name=options.application_name,
        version=options.version,
        deployment_type="pkg_application.c_deploy_type_initial",
        title="deployment",
        registrations=registrations,
        body=sections,
    )


def _render_update(
    options: GenerationOptions,
    objects: dict[str, ObjectFile],
    lifecycle: list[LifecycleFile],
    changed: dict[str, str],
    *,
    object_order: dict[str, int] | None = None,
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    lifecycle_by_key = {(item.directory, item.name.upper(), item.action): item for item in lifecycle}
    lifecycle_actions: dict[tuple[str, str], set[str]] = {}
    for item in lifecycle:
        key = (item.directory, item.name.upper())
        lifecycle_actions.setdefault(key, set()).add(item.action)
        if item.action in {"alter", "recreate"} and item.directory != "Tables":
            raise DbpmError(f"{item.action.title()} scripts are supported only for tables: {item.path}")
    for key, actions in lifecycle_actions.items():
        if "alter" in actions and "recreate" in actions:
            raise DbpmError(f"Table {key[1]} has both alter and recreate scripts")
        if "drop" in actions and actions.intersection({"alter", "recreate"}):
            raise DbpmError(f"Object {key[1]} has conflicting drop and evolution scripts")
    changed_objects = {
        path: _object_file(path)
        for path, status in changed.items()
        if status != "D" and _object_file(path) is not None
    }
    deleted_objects = {
        path: _object_file(path)
        for path, status in changed.items()
        if status == "D" and _object_file(path) is not None
    }

    registrations: dict[tuple[str, str], ObjectFile] = {}
    drops: dict[tuple[str, str], LifecycleFile] = {}
    alters: list[LifecycleFile] = []
    recreates: list[tuple[LifecycleFile, ObjectFile]] = []
    new_tables: list[ObjectFile] = []
    replaceable: list[ObjectFile] = []
    commented: list[str] = []

    for path, item in changed_objects.items():
        assert item is not None
        status = changed[path]
        if item.directory == "Tables":
            key = (item.directory, item.name.upper())
            alter = lifecycle_by_key.get((*key, "alter"))
            recreate = lifecycle_by_key.get((*key, "recreate"))
            if status == "A":
                if alter or recreate:
                    raise DbpmError(
                        f"New table {item.name} must not have an alter or recreate script"
                    )
                new_tables.append(item)
                _register(registrations, item)
            elif alter:
                alters.append(alter)
                _register(registrations, item)
            elif recreate:
                recreates.append((recreate, item))
                _register(registrations, item)
            else:
                warning = (
                    f"{item.path} changed without a matching alter or recreate script"
                )
                warnings.append(warning)
                commented.append(
                    f"-- {_include_path(options.release_upgrade_output, item.path)} "
                    f"-- WARNING: missing alter or recreate script"
                )
            continue
        if item.directory != "Metadata":
            _register(registrations, item)
        replaceable.append(item)

    table_objects = {
        (item.directory, item.name.upper()): item
        for item in objects.values()
        if item.directory == "Tables"
    }
    used_alters = {item.path for item in alters}
    used_recreates = {item.path for item, _ in recreates}
    for item in lifecycle:
        key = (item.directory, item.name.upper())
        canonical = table_objects.get(key)
        if item.action == "alter" and item.path not in used_alters:
            if canonical is None:
                raise DbpmError(f"Alter script {item.path} has no canonical table DDL")
            alters.append(item)
            _register(registrations, canonical)
        if item.action == "recreate" and item.path not in used_recreates:
            if canonical is None:
                raise DbpmError(f"Recreate script {item.path} has no canonical table DDL")
            recreates.append((item, canonical))
            _register(registrations, canonical)

    deleted_keys: set[tuple[str, str]] = set()
    for item in deleted_objects.values():
        assert item is not None
        key = (item.directory, item.name.upper())
        if key in deleted_keys:
            continue
        deleted_keys.add(key)
        drop = lifecycle_by_key.get((*key, "drop"))
        if drop:
            drops[key] = drop
        else:
            warning = f"{item.path} was deleted without a matching drop script"
            warnings.append(warning)
            commented.append(f"-- TODO: {warning}")

    for item in lifecycle:
        if item.action == "drop":
            drops.setdefault((item.directory, item.name.upper()), item)

    body_parts: list[str] = []
    body_parts.extend(_render_lifecycle_section(options.release_upgrade_output, "Dropping Removed Objects", drops.values()))
    body_parts.extend(_render_lifecycle_section(options.release_upgrade_output, "Altering Tables", alters))
    if recreates:
        body_parts.extend(["PROMPT Recreating Tables"])
        for recreate, canonical in sorted(recreates, key=lambda pair: pair[0].path.lower()):
            body_parts.append(_include_path(options.release_upgrade_output, recreate.path))
            body_parts.append(_include_path(options.release_upgrade_output, canonical.path))
        body_parts.append("")
    body_parts.extend(
        _render_object_sections(options.release_upgrade_output, new_tables, include_metadata=False, object_order=object_order)
    )
    body_parts.extend(
        _render_object_sections(options.release_upgrade_output, replaceable, include_metadata=True, object_order=object_order)
    )
    if commented:
        body_parts.extend(["PROMPT Review Unresolved Object Changes", *sorted(commented), ""])

    return (
        _render_deployment(
            application_name=options.application_name,
            version=options.version,
            deployment_type=options.deployment_type,
            title="update",
            registrations=sorted(registrations.values(), key=_object_sort_key),
            body=body_parts,
        ),
        warnings,
    )


def _render_deployment(
    *,
    application_name: str,
    version: str,
    deployment_type: str,
    title: str,
    registrations: Iterable[ObjectFile],
    body: list[str],
) -> str:
    major, minor, patch = parse_version(version)
    lines = [
        "SET DEFINE ON",
        f"DEFINE APPLICATION_NAME = '{application_name}'",
        f"DEFINE DEPLOY_VERSION_MAJOR = '{major}'",
        f"DEFINE DEPLOY_VERSION_MINOR = '{minor}'",
        f"DEFINE DEPLOY_VERSION_PATCH = '{patch}'",
        "DEFINE DEPLOY_COMMIT_HASH = '&&1'",
        "",
        "COLUMN CURRENT_SCHEMA new_value CURRENT_SCHEMA",
        "SELECT sys_context('USERENV','CURRENT_SCHEMA') AS CURRENT_SCHEMA FROM DUAL;",
        "",
        f"SPOOL {title}.&&APPLICATION_NAME..&&CURRENT_SCHEMA..&&DEPLOY_VERSION_MAJOR..&&DEPLOY_VERSION_MINOR..&&DEPLOY_VERSION_PATCH..log",
        "",
        "SET AUTOPRINT ON",
        "SET SERVEROUTPUT ON",
        "SET SQLBLANKLINES ON",
        "",
        "WHENEVER SQLERROR EXIT FAILURE",
        "WHENEVER OSERROR EXIT FAILURE",
        "",
        f"PROMPT Beginning {title} of &&APPLICATION_NAME",
        "",
        "BEGIN",
        "   pkg_application.begin_deployment_p",
        "      ( ip_deploy_commit_hash => '&&DEPLOY_COMMIT_HASH'",
        "      , ip_application_name   => '&&APPLICATION_NAME'",
        "      , ip_major_version      => &&DEPLOY_VERSION_MAJOR",
        "      , ip_minor_version      => &&DEPLOY_VERSION_MINOR",
        "      , ip_patch_version      => &&DEPLOY_VERSION_PATCH",
        f"      , ip_deployment_type    => {deployment_type}",
        "      );",
        "END;",
        "/",
        "",
        "PROMPT Registering Objects",
    ]
    lines.extend(_registration_sql(item) for item in registrations)
    lines.extend(["", *body])
    lines.extend(
        [
            "PROMPT Recompiling invalid objects",
            "BEGIN",
            "   DBMS_UTILITY.COMPILE_SCHEMA",
            "      ( schema         => SYS_CONTEXT('USERENV','CURRENT_SCHEMA')",
            "      , compile_all    => FALSE",
            "      , reuse_settings => TRUE",
            "      );",
            "END;",
            "/",
            "",
            "EXEC pkg_application.validate_objects_p(ip_application_name => '&&APPLICATION_NAME');",
            "EXEC pkg_application.validate_sys_privs_p(ip_application_name => '&&APPLICATION_NAME');",
            "EXEC pkg_application.set_deployment_complete_p(ip_application_name => '&&APPLICATION_NAME');",
            "",
            f"PROMPT &&APPLICATION_NAME {title} complete",
            "",
            "SPOOL OFF",
            "EXIT SUCCESS",
            "",
        ]
    )
    return "\n".join(lines)


def _render_object_sections(
    output_path: str,
    objects: Iterable[ObjectFile],
    *,
    include_metadata: bool,
    object_order: dict[str, int] | None = None,
) -> list[str]:
    grouped: dict[str, list[ObjectFile]] = {}
    for item in objects:
        if item.directory == "Metadata" and not include_metadata:
            continue
        grouped.setdefault(item.group, []).append(item)
    lines: list[str] = []
    for group in _group_order():
        items = grouped.get(group, [])
        if not items:
            continue
        lines.append(f"PROMPT Deploying {GROUP_LABELS[group]}")
        if object_order:
            sorted_items = sorted(items, key=lambda v: (object_order.get(v.path, len(object_order)), v.path.lower()))
        else:
            sorted_items = sorted(items, key=lambda v: v.path.lower())
        lines.extend(_include_path(output_path, item.path) for item in sorted_items)
        lines.append("")
    return lines


def _render_lifecycle_section(
    output_path: str,
    label: str,
    items: Iterable[LifecycleFile],
) -> list[str]:
    ordered = sorted(items, key=lambda item: item.path.lower())
    if not ordered:
        return []
    return [
        f"PROMPT {label}",
        *(_include_path(output_path, item.path) for item in ordered),
        "",
    ]


def _render_pointer(options: GenerationOptions) -> str:
    return "\n".join(
        [
            "SET DEFINE ON",
            "SET SHOWMODE OFF",
            "",
            "WHENEVER SQLERROR EXIT FAILURE",
            "WHENEVER OSERROR EXIT FAILURE",
            "",
            f"{_include_path(options.upgrade_pointer_output, options.release_upgrade_output)} &&1",
            "",
        ]
    )


def _registration_sql(item: ObjectFile) -> str:
    return (
        "EXEC pkg_application.add_object_p("
        f"ip_application_name => '&&APPLICATION_NAME', "
        f"ip_object_name => '{item.name.upper()}', "
        f"ip_object_type => {item.object_constant});"
    )


def _register(registrations: dict[tuple[str, str], ObjectFile], item: ObjectFile) -> None:
    if item.object_constant:
        registrations[(item.name.upper(), item.object_constant)] = item


def _object_file(path: str) -> ObjectFile | None:
    parts = PurePosixPath(path).parts
    if len(parts) != 2 or parts[0] not in OBJECT_DIRECTORIES:
        return None
    if _lifecycle_file(path):
        return None
    directory, filename = parts
    lower = filename.lower()
    if directory == "Packages":
        if lower.endswith(".pks"):
            return ObjectFile(path, directory, filename[:-4], "Packages:spec", OBJECT_CONSTANTS["Packages:spec"])
        if lower.endswith(".pkb"):
            return ObjectFile(path, directory, filename[:-4], "Packages:body", OBJECT_CONSTANTS["Packages:body"])
        return None
    if directory == "Types":
        if lower.endswith(".tps"):
            return ObjectFile(path, directory, filename[:-4], "Types:spec", OBJECT_CONSTANTS["Types:spec"])
        if lower.endswith(".tpb"):
            return ObjectFile(path, directory, filename[:-4], "Types:body", OBJECT_CONSTANTS["Types:body"])
        if lower.endswith(".sql"):
            return ObjectFile(path, directory, filename[:-4], "Types", OBJECT_CONSTANTS["Types"])
        return None
    if not lower.endswith(".sql") and directory != "Metadata":
        return None
    name = filename[:-4] if lower.endswith(".sql") else filename
    if directory == "Procedures" and name.lower().endswith(".prc"):
        name = name[:-4]
    if directory == "Functions" and name.lower().endswith(".fnc"):
        name = name[:-4]
    if directory == "Metadata":
        return ObjectFile(path, directory, name, "Metadata", None)
    return ObjectFile(path, directory, name, directory, OBJECT_CONSTANTS[directory])


def _lifecycle_file(path: str) -> LifecycleFile | None:
    match = LIFECYCLE_RE.match(path)
    if not match or match.group("directory") not in OBJECT_DIRECTORIES:
        return None
    return LifecycleFile(
        path=path,
        directory=match.group("directory"),
        name=match.group("object"),
        action=match.group("action").lower(),
        version=match.group("version"),
    )


def _tree_paths(git_root: Path, subpath: Path, ref: str) -> list[str]:
    if subpath == Path("."):
        dirs = list(OBJECT_DIRECTORIES)
        prefix = ""
    else:
        posix_sub = subpath.as_posix()
        dirs = [f"{posix_sub}/{d}" for d in OBJECT_DIRECTORIES]
        prefix = posix_sub + "/"
    output = _git(git_root, "ls-tree", "-r", "--name-only", ref, "--", *dirs)
    return [line[len(prefix):] for line in output.splitlines() if line]


def _diff_paths(git_root: Path, subpath: Path, from_ref: str, to_ref: str) -> dict[str, str]:
    if subpath == Path("."):
        dirs = list(OBJECT_DIRECTORIES)
        prefix = ""
    else:
        posix_sub = subpath.as_posix()
        dirs = [f"{posix_sub}/{d}" for d in OBJECT_DIRECTORIES]
        prefix = posix_sub + "/"
    output = _git(
        git_root,
        "diff",
        "--name-status",
        "--find-renames",
        from_ref,
        to_ref,
        "--",
        *dirs,
    )
    changed: dict[str, str] = {}
    for line in output.splitlines():
        fields = line.split("\t")
        status = fields[0][0]
        if status == "R":
            changed[fields[1][len(prefix):]] = "D"
            changed[fields[2][len(prefix):]] = "A"
        else:
            changed[fields[1][len(prefix):]] = status
    return changed


def _manifest_at_ref(git_root: Path, subpath: Path, ref: str):
    for name in MANIFEST_NAMES:
        git_path = name if subpath == Path(".") else f"{subpath.as_posix()}/{name}"
        text = _git_optional(git_root, "show", f"{ref}:{git_path}")
        if text is None:
            continue
        manifest = parse_manifest(text, name)
        try:
            import yaml

            raw = yaml.safe_load(text)
        except Exception:
            raw = {}
        return manifest, raw if isinstance(raw, dict) else {}
    return None, {}


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DbpmError("git is required for script generation") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise DbpmError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _git_optional(root: Path, *args: str) -> str | None:
    try:
        return _git(root, *args)
    except DbpmError:
        return None


def _include_path(output_path: str, source_path: str) -> str:
    parent = PurePosixPath(output_path).parent
    relative = os.path.relpath(source_path, parent.as_posix()).replace(os.sep, "/")
    return f"@@{relative}"


def _extract_table_refs(ddl_text: str) -> set[str]:
    return {m.upper() for m in re.findall(r'\bREFERENCES\s+(?:\w+\.)?(\w+)\b', ddl_text, re.IGNORECASE)}


def _topological_sort(names: list[str], deps: dict[str, set[str]]) -> list[str]:
    name_set = set(names)
    filtered = {n: {d for d in deps.get(n, set()) if d in name_set} for n in names}
    in_degree = {n: len(filtered[n]) for n in names}
    dependents: dict[str, list[str]] = {n: [] for n in names}
    for n, n_deps in filtered.items():
        for d in n_deps:
            dependents[d].append(n)
    ready = sorted(n for n in names if in_degree[n] == 0)
    result: list[str] = []
    while ready:
        n = ready.pop(0)
        result.append(n)
        newly_ready = []
        for dep in dependents[n]:
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                newly_ready.append(dep)
        ready = sorted(ready + newly_ready)
    if len(result) < len(names):
        cycle = sorted(n for n in names if n not in set(result))
        raise DbpmError(f"Circular table FK dependency detected: {', '.join(cycle)}")
    return result


def _compute_object_order(
    objects: dict[str, ObjectFile],
    git_root: Path,
    subpath: Path,
    ref: str,
) -> dict[str, int]:
    table_objects = [obj for obj in objects.values() if obj.directory == "Tables"]
    metadata_objects = [obj for obj in objects.values() if obj.directory == "Metadata"]
    if not table_objects:
        return {}
    subpath_prefix = "" if subpath == Path(".") else subpath.as_posix() + "/"
    deps: dict[str, set[str]] = {}
    for obj in table_objects:
        content = _git_optional(git_root, "show", f"{ref}:{subpath_prefix}{obj.path}")
        if content:
            deps[obj.name.upper()] = _extract_table_refs(content)
    table_names = [obj.name.upper() for obj in table_objects]
    sorted_names = _topological_sort(table_names, deps)
    name_to_pos = {name: i for i, name in enumerate(sorted_names)}
    result: dict[str, int] = {}
    for obj in table_objects:
        result[obj.path] = name_to_pos[obj.name.upper()]
    for obj in metadata_objects:
        prefix = obj.name.split(".")[0].upper() if "." in obj.name else obj.name.upper()
        result[obj.path] = name_to_pos.get(prefix, len(sorted_names))
    return result


def _object_sort_key(item: ObjectFile) -> tuple[int, str]:
    order = {group: index for index, group in enumerate(_group_order())}
    return order[item.group], item.path.lower()


def _group_order() -> tuple[str, ...]:
    return (
        "Sequences",
        "Tables",
        "Types:spec",
        "Types",
        "Types:body",
        "Views",
        "Functions",
        "Procedures",
        "Packages:spec",
        "Packages:body",
        "Metadata",
    )


def _normalize_output(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise DbpmError(f"Generated output must be inside the repository: {value}")
    return path.as_posix()


def _application_name(name: str) -> str:
    return name.replace("-", "_").upper()


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _deployment_type(target: str, override: str | None, previous: str | None) -> str:
    constants = {
        "major": "pkg_application.c_deploy_type_major",
        "minor": "pkg_application.c_deploy_type_minor",
        "patch": "pkg_application.c_deploy_type_patch",
    }
    if override:
        try:
            return constants[override.lower()]
        except KeyError as exc:
            raise DbpmError("--deployment-type must be major, minor, or patch") from exc

    target_parts = parse_version(target)
    if previous:
        previous_parts = parse_version(previous)
        if target_parts[0] > previous_parts[0]:
            return constants["major"]
        if target_parts[1] > previous_parts[1]:
            return constants["minor"]
        return constants["patch"]
    if target_parts[2] > 0:
        return constants["patch"]
    if target_parts[1] > 0:
        return constants["minor"]
    return constants["major"]


def _version_from_ref(ref: str) -> str | None:
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", ref, re.IGNORECASE)
    return match.group(1) if match else None
