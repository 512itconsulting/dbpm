from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .errors import DbpmError


ConnectKind = Literal["connect-string", "sqlcl-name"]


@dataclass(frozen=True)
class ConnectSpec:
    kind: ConnectKind
    value: str


def connect_string(value: str) -> ConnectSpec:
    return ConnectSpec(kind="connect-string", value=value)


def sqlcl_name(value: str) -> ConnectSpec:
    return ConnectSpec(kind="sqlcl-name", value=value)


def normalize_connect(connect: str | ConnectSpec) -> ConnectSpec:
    if isinstance(connect, ConnectSpec):
        return connect
    return connect_string(connect)


def build_sql_command(
    *,
    runner: str,
    connect: str | ConnectSpec,
    script_ref: object,
    arguments: list[object] | None = None,
    silent: bool = False,
) -> list[str]:
    spec = normalize_connect(connect)
    args = [str(arg) for arg in arguments or []]
    script_arg = f"@{script_ref}"
    if spec.kind == "connect-string":
        command = [runner, "-L"]
        if silent:
            command.append("-S")
        return [*command, spec.value, script_arg, *args]
    return [runner, "-S", "-L", "-name", spec.value, script_arg, *args]


def validate_connect_spec(*, connect: ConnectSpec, runner: str) -> None:
    if not connect.value:
        raise DbpmError("Database access requires --connect/DBPM_CONNECT or --connect-name/DBPM_CONNECT_NAME")
    if connect.kind == "sqlcl-name" and _is_clearly_sqlplus(runner):
        raise DbpmError("SQLcl saved connections require a SQLcl runner; use --runner sql or DBPM_SQL_RUNNER=sql")


def _is_clearly_sqlplus(runner: str) -> bool:
    name = Path(runner).name.lower()
    return name in {"sqlplus", "sqlplus.exe"}
