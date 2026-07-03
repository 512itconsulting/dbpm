# Security Policy

dbpm executes Oracle SQL/PLSQL deployment manifests, resolves package
artifacts, records deployment provenance, and can publish or install packages
from remote repositories. Please report security issues privately before
opening a public issue.

## Supported Versions

Security fixes target the current released dbpm series and the default branch.
Older releases may receive fixes when practical, but users should expect to
upgrade to the latest release for security updates.

## Reporting a Vulnerability

Report suspected vulnerabilities through GitHub's private vulnerability
reporting feature for this repository. If that is unavailable, contact the
repository owner privately before disclosing details in a public issue.

Please include:

- The affected dbpm version or commit.
- The command, source type, manifest, or workflow involved.
- Whether the issue requires database credentials, package publishing rights,
  repository write access, or only package consumption.
- A minimal reproduction, redacted logs, and any relevant Oracle, SQLcl, or
  SQL*Plus versions.
- Whether the issue can affect deployment provenance, artifact integrity,
  credential exposure, destructive reinstall behavior, or arbitrary SQL
  execution beyond the requested deployment.

Do not include production credentials, private keys, tokens, customer data, or
full unredacted database logs.

## Scope

Security-sensitive areas include:

- Credential handling for Oracle connections, GitHub Packages, Maven
  repositories, registries, and signing keys.
- Artifact integrity, checksum verification, signature verification, and cache
  behavior.
- Provenance injection and protection against misleading deployment metadata.
- Environment policy checks and prevention of unintended destructive
  reinstall behavior.
- SQL runner invocation, generated manifests, and execution logs.

Normal deployment scripts are expected to execute SQL/PLSQL supplied by a
trusted package artifact. Reports are most useful when they show dbpm doing
something outside the operator's explicit request or outside the package
metadata that was resolved.

