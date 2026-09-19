# Implementation Plan Schema

Canonical structure and conventions for feature implementation plans. The goal:
a plan is a **status-trackable, executable document** — one file per feature
contour that you skim in 2 minutes to know *what is done*, *what is next*, and
*which design decisions are locked*. Depth moves to ARCH/SPEC-style source docs;
the plan stays a roadmap with per-phase verification.

Uses the concise step/status format established in
`docs/development/implementation/DOC_PROC_DEV_FLOW/IMPL_PLAN.md` (dev flow) and
`docs/development/ORGS/IMPL_PLAN.md` (organization domain).

Status legend: `[ ]` pending · `[x]` done.

---

## 1. When to use

- Any multi-phase feature contour that touches more than one app/package or
  spans more than a week of work.
- The plan is created up front, then **updated after every phase** (status →
  pause → confirm with the user → next phase).
- One-shot, single-commit changes do **not** need a plan file.

## 2. File conventions

| Rule | Guidance |
|---|---|
| Location | `docs/development/implementation/<FEATURE>/IMPL_PLAN.md` (sibling of `development/operational/CONTRIBUTING.md`, `development/operational/MIGRATIONS.md`) |
| Status markers | `[x]` done / `[ ]` pending — mirrored in **three places**: section heading, execution-summary table, implementation-order list |
| Revision notes | Block under the intro; added when the plan is restructured, a phase set is added/removed, or a started phase's plan changes. Record *what changed* and the base doc when the format is derived from another plan. Never rewrite history. |
| Source-of-depth | Link ARCH/SPEC docs in the intro; the plan keeps condensed summaries only (§4) |
| Tone | Terse tables over prose; per-phase blocks over paragraphs |

## 3. Anatomy (top-level spine)

| § | Section | Purpose | Required |
|---|---|---|---|
| 0 | Overview | Current vs target flow diagrams; key mechanisms; **locked invariants** (rules all phases must obey) | yes |
| 1 | Execution summary | One table `Phase \| Scope \| Status` for the whole contour | yes |
| 2 | Completed phases | Full blocks for done phases (see grammar below) | once ≥1 phase done |
| 3 | Pending phases | One-tight-block per not-started phase | yes |
| 4 | Locked design reference | Shared design decisions/SQL/migrations/endpoints that phases depend on; condensed from the source docs | when phases share a design base |
| 5 | Tests | Which suites/areas each phase exercises; the exact run/lint commands | yes |
| 6 | Implementation order | Numbered list; may reorder phases by dependency (with a parenthetical reason); each ends `[x]`/`[ ]` | yes |
| 7 | Notes | Gotchas (verified empirically), open decisions with chosen defaults, risks + mitigations; pointer to `CONTRIBUTING.md` conventions | yes |

## 4. Phase block grammar

### Completed phase

````markdown
### Phase N — Short name [x]

**Status.** One line: done + pointer to the "Phase N Implementation Status" block.

**Changes.** What was actually implemented (files/behaviors) — the diff to the
plan, not the plan itself.

**Verification.** Exact numbers + commands: "X tests pass (was Y, +Z); `uvx
ruff check ...` clean".

#### Phase N Implementation Status

- Files created / modified (paths only).
- Deviations from the initial plan (label explicitly: `Deviation:`),
  including pre-existing issues left untouched "per convention".
- Behavioral / empirical notes (e.g. ORM quirks, non-portable migrations).
- Verification recap + commit hash (`git log` short form).
- Next step (confirmed / pending — e.g. "confirmed Phase N+1").
````

### Pending phase

````markdown
### Phase N — Short name [ ]

DB <migration>. <service/table> + API routes. Tests: <what>. Deps: <Phases>.
**Accept:** observable acceptance criterion.
````

For `§0` diagrams: keep current vs target side-by-side or sequential; show the
existing pipeline as a shared spine so "no parallel architecture" is visible.

## 5. Rules of the game

1. **Status is mirrored in three places** — heading, summary table,
   implementation order. If a phase flips, update all three.
2. **Safety buffer before every phase** — a phase ends with tests + status
   update + a pause to confirm with the user; never chain phases automatically.
3. **Implementation Status is written after the fact** — it records what
   actually shipped (`Changes` section) and the runnable verification, so the
   plan doubles as a build log.
4. **Deviations are explicit** — any change from the plan (renames, skipped
   steps, behavior notes) is called out in the phase's Implementation Status,
   never silently absorbed.
5. **Verification states reality** — exact test counts, the command used, and
   the result. "Tests pass" alone is not enough.
6. **Depth lives outside the plan** — SQL dumps, full schema DDL, prompt/config
   YAML go in ARCH/SPEC/other reference files; the plan holds a condensed
   pointer and the decision, not the dump.
7. **Locked invariants come first (§0)** — anything a later phase must not
   violate (e.g. "document status mutated only in `documents.py`", "enums as
   VARCHAR") is stated up front, not discovered mid-scope.
8. **Open decisions are tracked** — §7 keeps unresolved choices with the chosen
   default marked, so a blocker is visible before it blocks.

## 6. Minimal skeleton

````markdown
# <Feature> — Implementation Plan

One-paragraph scope: what the contour delivers, "built on existing infra only —
no parallel architecture", depth sources (linked ARCH/SPEC docs).

**Revision 1** — initial plan.

Status legend: `[ ]` pending · `[x]` done.

---

## 0. Overview

**Current / target flow:** (ASCII diagram)

**Invariants (locked):** (bullets)

## 1. Execution summary

| Phase | Scope | Status |
|---|---|---|
| 1 | <scope> | [ ] |
| … | | |

## 2. Completed phases

### Phase 1 — <name> [x]
… (grammar above)

## 3. Pending phases

### Phase 2 — <name> [ ]
DB `0007`. … **Accept:** …

## 4. Locked design reference (when needed)

## 5. Tests

## 6. Implementation order

1. Phase 1 — <name>. [ ]

Each phase: implement → update this status → pause for confirmation.

## 7. Notes & conventions

### Gotchas (verified)
### Open decisions (defaults chosen)
### Risks (mitigations in place)
````

## 7. References

- Exemplar (completed-heavy): `docs/development/implementation/DOC_PROC_DEV_FLOW/IMPL_PLAN.md`
- Exemplar (spec-heavy, condensed): `docs/development/ORGS/IMPL_PLAN.md`
- Engineering conventions: `docs/development/CONTRIBUTING.md`
- Migration rules: `docs/development/MIGRATIONS.md`