# Web E2E Testing Guide (`apps/web`)

> Comprehensive reference for the Playwright end-to-end suite introduced in
> **Milestone M7** of `IMPLEMENTATION_PLAN.md`. Read this before writing or
> debugging E2E tests.
>
> Companion docs: `IMPLEMENTATION_PLAN.md` (roadmap & tracking),
> `OAI_STYLE_GUIDE.md` (visual system), `../docs/development/TESTING.md`
> (Python-side testing).

---

## 1. What this suite is

Three Playwright specs drive **the real application against the real dev
stack** — Vite build served to a headless Chromium, FastAPI `account-api` on
`:8000`, PostgreSQL, Redis, RabbitMQ — with **zero mocks**:

| Spec | Proves |
|---|---|
| `tests/e2e/happy-path.spec.ts` › *client happy path* | The MVP-1 vertical slice end-to-end: OTP login → dashboard → PDF upload via mobile sheet → toast + list entry with status chip → detail page → stepper hint → tabs → extracted-data empty state |
| `happy-path.spec.ts` › *axe + 320px* | Every authenticated page passes axe WCAG 2.0/2.1 A+AA (critical & serious = failing) and has **zero horizontal overflow at 320px** |
| `tests/e2e/isolation.spec.ts` | Authorization: a second, unrelated account opening patient A's document URL gets the calm «Нет доступа / Документ не найден» screen and **none** of A's data leaks into the DOM |

Why this suite exists in the first place — it earned its keep on day one by
catching two critical bugs unit tests could never see:

1. `main.tsx` had lost its `import "@/styles/globals.css"` since M0 — **the
   entire app rendered unstyled** (no breakpoints, both navigations visible,
   dead design tokens).
2. `getMe()` used plain `unwrap()` instead of the `authed()` wrapper — after a
   cold reload, `/patients/me` was silently refreshed-and-replayed but
   `/auth/me` never was, breaking session restore.

---

## 2. Layout

```
apps/web/
├── playwright.config.ts          # runtime config (below)
└── tests/
    ├── setup.ts                  # vitest setup — NOT used by Playwright
    └── e2e/
        ├── helpers/
        │   └── auth.ts           # OTP acquisition + Redis reader
        ├── fixtures/
        │   └── sample.pdf        # minimal hand-written valid PDF
        ├── happy-path.spec.ts
        └── isolation.spec.ts
```

### `playwright.config.ts`

| Setting | Value | Meaning |
|---|---|---|
| `testDir` | `./tests/e2e` | Specs live beside unit tests but are never mixed |
| `timeout` | 30 s | Per test; heavy flows raise it inline (`test.setTimeout`) |
| `retries` | `process.env.CI ? 1 : 0` | One automatic retry in CI only |
| `use.baseURL` | `http://localhost:5173` | All `page.goto("/…")` are relative |
| `trace` | `"on-first-retry"` | Trace recorded when a CI retry kicks in |
| `webServer` | `npm run dev` on `:5173`, `reuseExistingServer: !CI` | Playwright boots Vite itself; locally it will reuse your running dev server, in CI always a fresh one |

**Not** configured here: browsers auto-install. Install once with
`npx playwright install chromium` (`make test-e2e` does it for you).

---

## 3. Prerequisites

The suite talks to real services. Before running:

```bash
# 1. Infra + backend + workers (postgres :5432, redis :6379,
#    rabbitmq :5672, account-api :8000 — migrations applied automatically)
make compose-dev

# 2. Verify the API answers (401 expected without a token)
curl -i http://localhost:8000/api/v1/auth/me | head -1   # → HTTP/1.1 401
```

Notes:

- If you run the backend outside Docker instead, it must still reach the same
  Postgres/Redis/RabbitMQ, and Redis must be the instance the helper reads.
- Stop stray Vite processes on `:5173` (`lsof -ti:5173 | xargs kill`) —
  locally the config reuses whatever is already listening, which may be stale.

---

## 4. Running the tests

```bash
make test-e2e                 # install chromium if needed + run everything
cd apps/web && npx playwright test          # same, explicit
npx playwright test happy-path              # one file (filename substring)
npx playwright test -g "axe"                # by test title substring
npx playwright test --headed                # watch the browser
npx playwright test --ui                    # interactive UI mode (best debugger)
npx playwright test --debug                 # step-through inspector
npx playwright show-report                  # HTML report after a run
npx playwright show-trace test-results/<…>/trace.zip   # deep-dive a failure
```

Runtime knobs:

| Env var | Default | Purpose |
|---|---|---|
| `REDIS_CONTAINER` | `development-redis-1` | Container the OTP helper reads; CI passes the service-container id instead |

---

## 5. How authentication works in tests

There are **no passwords** in this product — auth is one-time codes
(`POST /auth/request-otp` → user receives code → `POST /auth/verify`). The E2E
suite reproduces this without involving e-mail:

```
spec                     helpers/auth.ts
─────                    ──────────────────────────────────────────────
page.goto /login
fill identity            uniqueIdentity()      e2e-<ts>-<rand>@example.com
click «Получить код»     requestOtp(identity)  curl POST :8000 → asserts "OTP sent"
(OTP screen shows)       readOtpCode(identity) docker exec <REDIS_CONTAINER>
                                               redis-cli GET otp:code:<identity>
fill Цифра 1..6 из 6     (auto-submits on 6th digit → tokens stored → redirect /)
```

Implementation details worth knowing:

- **Unique identities per login.** The backend rate-limits `request-otp` to
  1/min *per identity*, so every login mints a fresh address. A side effect:
  every run creates accounts (`e2e-…@example.com`) in the dev database — they
  are inert and can be wiped anytime.
- **Codes live in Redis at `otp:code:{identity}`** (TTL 300 s). The
  notification-worker only *reads* the event payload to send e-mail — it never
  deletes the key, and in dev the SMTP provider failing does not affect us.
- **`readOtpCode` retries for up to 10 s** (500 ms interval, lock-free
  `Atomics.wait` sleep) because a transiently empty read was observed under
  parallel load. A non-6-digit value after the deadline fails the test with
  the last observed raw output in the message.
- **`requestOtp` asserts the response body contains `OTP sent`**, so a 429
  rate-limit response fails fast with the body in the error instead of a
  confusing missing-code error later.

---

## 6. Walkthrough: what each assertion buys you

### 6.1 Happy path (mobile viewport 390×844 — SG §42 flows)

| Step | Assertion / action | Guards against |
|---|---|---|
| Login | subtitle «Мы отправили код на …» visible | OTP screen actually reached |
| OTP cells | `getByLabel("Цифра N из 6")` filled digit-by-digit | Accessible cell labeling stays intact |
| Redirect | URL `/` + `<h1>` within 15 s | Session bootstrap (me + patient prefetch) completes; guards don't bounce |
| Navigation | bottom-nav link «Документы» → URL `/documents` | Mobile nav renders & routes |
| Empty state | «Пока нет документов» visible | Four-states rule: empty branch works |
| Upload | open sheet → dialog role visible → `setInputFiles` on hidden input #2 → `Escape` closes sheet | Sheet focus/ARIA contract; hidden inputs wired to the right handlers (input #0 is the camera-capture input) |
| Queued | toast «Документ загружен» + card `hasText "e2e-blood-test"` with status chip | Machine QUEUED → list invalidation → refetch pipeline; note: **backend derives the title from the filename stem**, so matchers deliberately omit `.pdf` |
| Detail | URL matches `/documents/<uuid>`; heading; honest hint «Обработка может занять время…» | Polling page loads; BK-6 honest-processing copy present while workers are stubs |
| Tabs | switch to «Извлечённая информация»; «Информация ещё извлекается» within 10 s | Tab primitive switches panels; extraction empty-state renders (query may still be in flight — hence the raised timeout; skeleton rows are `aria-hidden` and invisible to role queries, which previously made the panel *look* empty in snapshots) |

Fixture: `fixtures/sample.pdf` is a hand-written minimal-but-valid PDF that
passes the backend's magic-byte sniffing (`%PDF` header check).

### 6.2 Axe + overflow sweep (viewport forced to 320×720)

For each of `/`, `/documents`, `/medical-record`, `/profile`:

1. `h1` appears within 15 s **and** URL is not `/login` — proves silent
   session restore survives full page reloads (this exact check exposed the
   `getMe()` bug).
2. `document.scrollingElement.scrollWidth - clientWidth ≤ 0` — no horizontal
   scroll at the smallest supported width (SG §58). This caught a 1 px
   overflow from the documents-page header and forced its `flex-wrap` fix.
3. `AxeBuilder.withTags(["wcag2a", "wcag2aa"])` — violations with impact
   `critical` or `serious` fail the test; `moderate`/`minor` are reported but
   tolerated. This is what keeps the palette honest: it flagged SG §5's
   `#8A928C` muted-text color at 3.7:1 contrast, leading to the deliberate
   deviation documented in `tokens.css` (`#6B746C`, ≈4.6:1).

### 6.3 Isolation

Two **separate browser contexts** (= separate localStorage silos):

1. Context A logs in, uploads `private-a.pdf`, captures its `href`.
2. Context B (fresh account) navigates directly to A's document URL.
3. Assert B sees the access-denied/not-found screen **and**
   `toHaveCount(0)` for any node containing the filename — proving the
   backend ABAC denial (`403`) surfaces as UI, never as leaked content.

---

## 7. CI integration (`.github/workflows/test.yml` › `e2e` job)

The job rebuilds the whole world on ephemeral runners:

```
services: postgres:16 · redis:7 · rabbitmq:3-management   (healthchecked)
steps:
  uv sync --all-packages --frozen
  alembic upgrade head
  uvicorn app.main:app --app-dir apps/account-api --port 8000   (background)
  wait-for :8000/openapi.json
  npm ci && npx playwright install --with-deps chromium
  npx playwright test
  (on failure) upload apps/web/test-results/ as artifact, 7-day retention
```

Key differences from local runs:

| Concern | Local | CI |
|---|---|---|
| Vite server | reuses yours | always fresh (`reuseExistingServer: false` when `CI=1`) |
| Redis container | `development-redis-1` | `REDIS_CONTAINER=${{ job.services.redis.id }}` |
| Retries | 0 | 1 (with trace) |
| Dev credentials | from `infrastructure/development/.env` | inline job-level env (`ci-…` secrets ≥32 chars; backend accepts them because `APP_ENV≠production`) |

PR gating today: `test.yml` runs **python tests**, **web lint+unit+build**,
and this **e2e** job. Expect the e2e leg to be the slowest (~4–5 min).

---

## 8. Debugging a failure

1. **Read `test-results/<test-name>/error-context.md`** — Playwright writes a
   page snapshot (accessibility YAML), the error, and the relevant test source
   there on every failure. It resolves most mysteries without rerunning.
2. Reproduce interactively: `npx playwright test <filter> --headed` or
   `--debug` (inspector with pause/live locator picking). Best-of-breed is
   `--ui` mode: time-travel through every action with DOM/Diff panes.
3. If a retry happened in CI, download the `playwright-traces` artifact and
   open it with `npx playwright show-trace trace.zip`.
4. Network truth beats guessing: temporarily add
   `page.on("response", …)` logging filtered to `/api/` (this technique
   pinpointed the `getMe()` refresh bug — the replay request simply never
   fired).

---

## 9. Troubleshooting quick table

| Symptom | Likely cause | Fix |
|---|---|---|
| `net::ERR_CONNECTION_REFUSED :8000` in step logs | Backend not running | `make compose-dev` (or start account-api) |
| Test hangs on `:5173` / old UI shown | Stale Vite reused by `reuseExistingServer` | Kill port 5173, rerun |
| `request-otp failed: {"detail":"…wait…"} (429)` | Same identity twice inside 60 s | Shouldn't happen (unique identities); means helper was called twice for one identity — check for accidental double-clicks/submits |
| `no OTP code in redis …: ""` after retries | Wrong `REDIS_CONTAINER`; backend pointing at another Redis DB; key expired (>5 min between request & read) | Check env; confirm `docker exec <container> redis-cli KEYS 'otp:*'` manually |
| Strict-mode violation: locator resolved to 2 elements | Duplicate accessible names (we hit two identically-labeled `<nav>`s) | Give landmarks unique `aria-label`s; scope locators (`aside.getByRole(...)`) |
| Element "exists visually" but not found by role query | It's `aria-hidden` (e.g. loading skeletons) or display:none | Wait for the post-loading state instead; don't assert on skeleton internals |
| Contrast violation after palette edits | Token change dropped below 4.5:1 | Recompute ratio; SG §37 (WCAG) overrides SG §5 hex values |
| 1–2 px overflow failures at 320px | Fixed-width sibling next to long min-content text | Add `flex-wrap` + `min-w-0` to the row (see DocumentsPage header fix) |

---

## 10. Conventions for new tests

1. **Viewports**: declare intent per file/flow — `test.use({ viewport: { width: 390, height: 844 } })` for mobile-first flows; set explicitly (`setViewportSize`) when a test is *about* responsiveness (like the 320px sweep).
2. **Query like a user**: prefer `getByRole`, `getByLabel`, `getByText` with the exact **Russian strings imported from `src/lib/i18n/strings.ts`** (copy them literally into matchers). Reach for CSS/testids only as a last resort.
3. **Unique data**: every login uses `uniqueIdentity()`; uploaded filenames embed the scenario (`private-a.pdf`) so isolation checks can assert absence precisely.
4. **No PHI/token leakage**: never `console.log` payloads, tokens, or patient data — even in diagnostics you plan to delete (M7 removed such a temp spec). Error boundaries intentionally swallow route-error details.
5. **Timeouts are assertions about UX**: prefer raising `expect(..., { timeout })` over `waitForTimeout` sleeps; the only sanctioned sleep pattern lives inside `readOtpCode`'s poll loop.
6. **Keep specs independent**: each test logs in fresh (no cross-file state); use separate contexts when a scenario needs two principals.
7. **When you add a page**, add it to the axe/overflow `paths` array in the sweep test — that list is the enforcement net for §43 four-states + responsive rules.

---

## 11. Coverage map — plan §7 (M7) ↔ suite

| Plan task | Where implemented |
|---|---|
| Playwright happy path incl. OTP-from-Redis | `happy-path.spec.ts` › test 1 |
| Auth-isolation E2E | `isolation.spec.ts` |
| a11y pass (axe, reduced-motion, semantic buttons) | `happy-path.spec.ts` › test 2 (+ `prefers-reduced-motion` global CSS guard from M0 tokens) |
| 320px viewport sweep | `happy-path.spec.ts` › test 2 (per-path overflow probe) |
| Error boundaries; console.log cleanup; no PHI in logs | route `errorElement`s + `ErrorBoundary.tsx` (verified by `grep` — suite keeps it honest) |
| Touch-target audit | static classes audited (h-11/h-12 buttons, h-10 chips) — enforced informally; axe `target-size` can be added to `withTags` later if desired |

---

*Maintainer note: when the marker/AI workers stop being stubs (BK-6), extend
the happy path with a terminal-status wait (`Готов`) and an
extracted-values assertion — the polling hook already stops on terminal
statuses, so the test reduces to one more `expect`.*
