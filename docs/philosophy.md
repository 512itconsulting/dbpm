# Philosophy

## Introduction

dbpm is shaped by practical experience deploying Oracle database applications in large enterprise environments.

The project is based on several opinions about what works well, what fails at scale, and what modern database engineering should look like.

---

# Roll Forward, Not Roll Back

Rollback scripts are often unreliable in real-world systems.

Once:
- data changes
- external systems integrate
- downstream processes execute
- users interact with new structures

true rollback becomes difficult or impossible.

dbpm prioritizes:
- forward-only migrations
- corrective patches
- deterministic upgrade paths
- deployment safety

over the illusion of guaranteed rollback.

---

# Production Changes Reduce Velocity

Development velocity drops dramatically once software reaches production.

After deployment, engineering effort shifts toward:
- compatibility concerns
- migration safety
- operational coordination
- environment drift management
- deployment sequencing

dbpm aims to reduce this friction through:
- standardized packaging
- dependency tracking
- reproducible deployments
- explicit versioning

---

# Explicit Is Better Than Implicit

Hidden deployment assumptions create operational risk.

Dependencies, installation order, and environment requirements should be explicitly declared rather than inferred from tribal knowledge or deployment spreadsheets.

dbpm favors:
- manifests
- metadata
- version constraints
- declarative configuration

over implicit behavior.

One exception is Core itself: Core is the dbpm substrate and should be checked as a platform prerequisite rather than repeated as an ordinary dependency in every package's application dependency list.

---

# Immutable Artifacts

Deployments should use immutable versioned artifacts.

A package version should always represent:
- identical content
- identical metadata
- identical deployment behavior

across all environments.

Rebuilding or mutating released artifacts introduces risk and undermines reproducibility.

For released artifacts, dbpm should inject deployment provenance from the artifact metadata instead of relying on hard-coded SQL wrapper values.

End-user applications should be installed and patched from immutable artifacts too. They may have richer lifecycle scripts than reusable libraries, but dbpm should still own resolution, planning, Core verification, provenance injection, and execution orchestration.

Applications should commit lockfiles for release-oriented deployments. A lockfile turns dependency constraints into exact artifact identities and protects deployments from mutable upstream state.

---

# Destructive Actions Require Intent

Full reinstall workflows are useful during active development, but they can destroy application-owned objects and usage data.

dbpm should make destructive reinstall a distinct, explicit mode. Normal install and upgrade flows should avoid calling Core cleanup APIs such as `pkg_application.delete_application_p` unless the operator deliberately chose a destructive workflow and Core deployment-lock policy permits it.

---

# The Database Is a Software Platform

Databases are often treated as passive persistence layers.

In reality, enterprise Oracle systems frequently contain:
- business logic
- orchestration
- transformation engines
- APIs
- scheduling
- validation
- event processing

These systems deserve the same engineering rigor applied to application platforms.

---

# Reuse Should Be Easy

Many organizations repeatedly reinvent:
- utility packages
- logging frameworks
- assertion libraries
- deployment helpers
- metadata utilities

because distributing reusable PL/SQL code is difficult.

dbpm aims to normalize reusable database libraries and shared components.

That only works if consumption is substantially easier than publication. Package producers may use richer build and publishing tooling, including Maven-compatible repositories, but consumers should be able to install through dbpm without learning Maven or installing a JDK solely for package retrieval.

dbpm should prefer transparent HTTP(S) artifact downloads for consumer installs, while still allowing producer workflows to publish into established artifact repositories.

Consumers should not need to vendor dependent repositories into an application just to make deployments stable. Stability should come from immutable artifacts, lockfiles, local caches, and trusted mirrors.

If a package publisher deletes an artifact, dbpm should continue only when the exact locked artifact is available from a configured trusted source and matches its checksum. Otherwise, failing loudly is safer than silently choosing a substitute.

---

# Deployment State Matters

Successful deployment depends not only on:
- target version

but also:
- current schema state
- installed dependencies
- environment configuration
- prior migrations
- data conditions

dbpm treats deployment state as a first-class concern.

---

# Database Development Is Engineering

Database work is often incorrectly framed as:
- scripting
- administration
- maintenance

rather than software engineering.

dbpm assumes:
- testing matters
- versioning matters
- automation matters
- architecture matters
- package boundaries matter

because database systems are software systems.

---

# Practicality Over Purity

dbpm is intended for real enterprise environments.

The project prioritizes:
- operational reliability
- compatibility with existing workflows
- incremental adoption
- transparency
- observability

over theoretical elegance.

---

# Respect the DBA

DBAs are not obstacles to automation.

Enterprise databases require:
- governance
- operational oversight
- performance management
- security controls
- backup and recovery planning

dbpm should complement DBA workflows rather than attempting to bypass them.
