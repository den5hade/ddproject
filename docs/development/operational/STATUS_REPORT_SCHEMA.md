# Status Report Schema

Conventions for project status snapshots. One file per snapshot at `docs/archive/PROJECT_STATUS_YYMMDD.md`. Living status at `docs/PROJECT_STATUS.md` with latest-snapshot symlink at `docs/PROJECT_STATUS_LATEST.md`.

## When to Create a Snapshot
- Major milestone completion
- Before/after significant refactors
- Quarterly or on demand

## Snapshot Naming
```
docs/archive/PROJECT_STATUS_YYMMDD.md
```
Example: `PROJECT_STATUS_090526.md` (5 September 2026)

## Status Markers (for tables)
| Marker | Meaning |
|--------|---------|
| `[x]` | Implemented & working in code |
| `[~]` | Partial — foundation exists, needs finishing |
| `[ ]` | Not implemented / deferred |

## Layer Maturity Indicators (for maturity matrix)
| Icon | Meaning |
|------|---------|
| ✅ | Complete / verified |
| 🟢 | Implemented in code |
| 🟡 | In progress / foundation exists |
| 🔵 | Future / planned |

## Required Sections (for snapshots)
1. **Executive Summary** — 3-5 bullets, current stage
2. **Layer Status Tables** — Migrations, Domain Model, API, Auth, Pipeline, Packages, Frontend, Infra
3. **Near-Complete Items** (`[~]`) — what needs finishing
4. **Not Implemented** (`[ ]`) — next phases
5. **Maturity Matrix** — table with icons per layer
6. **Key Conclusions** — risks, next priorities
6. **Code Reference Map** — layer → file paths

## Table Formats
- **Migrations**: version, description, status
- **Domain Model**: entity, table, status
- **API**: contour, endpoints, status
- **Components**: package, status

## Living Status (`docs/PROJECT_STATUS.md`)
- English, concise (<200 lines)
- Updated in place (no date suffix)
- References latest snapshot via `docs/PROJECT_STATUS_LATEST.md` symlink

## Symlink: `docs/PROJECT_STATUS_LATEST.md`
Points to the most recent archive snapshot. Updated when a new snapshot is created.

```bash
ln -sf archive/PROJECT_STATUS_090526.md PROJECT_STATUS_LATEST.md
```

## Reference Example
`docs/archive/PROJECT_STATUS_090426.md` — comprehensive reference snapshot (2026-09-04)
`docs/archive/PROJECT_STATUS_090526.md` — code-based snapshot (2026-09-05)