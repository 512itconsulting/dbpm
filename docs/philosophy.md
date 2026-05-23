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

---

# Immutable Artifacts

Deployments should use immutable versioned artifacts.

A package version should always represent:
- identical content
- identical metadata
- identical deployment behavior

across all environments.

Rebuilding or mutating released artifacts introduces risk and undermines reproducibility.

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