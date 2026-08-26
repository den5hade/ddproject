# Contributing — `apps/web`

Frontend for the medical-documents platform: **Vite · React 18 · TypeScript
(strict) · Tailwind v4 · TanStack Query · React Hook Form + Zod**.

This document is the contract for changing frontend code. It encodes decisions
already made (see `IMPLEMENTATION_PLAN.md` §0 Decisions Log) and hard-won
lessons from real bugs — the "Common pitfalls" section (§9) is not theoretical.

> Companion docs: `IMPLEMENTATION_PLAN.md` (roadmap, architecture specs,
> milestone tracking) · `OAI_STYLE_GUIDE.md` (visual system) ·
> `WEB_GUIDE_E2E_TEST.md` (E2E deep-dive).

---

## 1. Quick start

```bash
# Prereqs: Node ≥ 20, npm, Docker (for the backend stack)
make setup-web          # npm install
make compose-dev        # postgres/redis/rabbitmq/account-api/workers (:8000)

make dev-web            # Vite on :5173 (proxies /api → :8000)
```

Daily loop:

```bash
make lint-web           # ESLint (must be clean)
make test-web           # Vitest unit/component tests (must be green)
make build-web          # tsc -b && vite build (type errors fail here)
make test-e2e           # Playwright vs live stack (when touching flows/pages)
make generate-api-types # regenerate TS types after ANY backend contract change
```

CI (`.github/workflows/test.yml`) enforces lint + unit + build on every PR and
runs the full E2E suite against a spun-up stack. If it's red locally it will be
red there — save yourself the push.

---

## 2. Where things go (layering rules)

```
src/
├── app/            # ROUTES ONLY. Thin pages that compose feature components.
│                   # Guards, lazy imports, errorElement wiring. No domain logic.
├── features/       # Domain slices. Each owns its api.ts / hooks.ts / schemas.ts /
│   │               # components/. Cross-feature imports only via hooks or lib.
│   └── <name>/
├── components/ui/  # Design-system primitives (shadcn-style). Zero domain
│                   # knowledge, zero feature imports. forwardRef REQUIRED.
├── lib/            # Infrastructure: api client, query keys, i18n strings,
│                   # utils. No React components except headless helpers.
└── styles/         # tokens.css = single source of visual truth.
```

Dependency direction: `app → features → lib`. Never the reverse.
`components/ui` imports nothing from `features/` or `app/`.

**Where does this code go?**

| You're adding… | It lives in |
|---|---|
| A screen | `app/<area>/<Name>Page.tsx` (thin) + `features/<domain>/components/` |
| A server call | `features/<domain>/api.ts` (typed via generated schema) |
| Cache orchestration | `features/<domain>/hooks.ts` using `lib/query/keys.ts` factories |
| Form validation | `features/<domain>/schemas.ts` (zod, mirroring backend constraints) |
| A reusable button-ish thing | `components/ui/` |
| A ru string | `lib/i18n/strings.ts` — nowhere else (§4.5) |

---

## 3. The non-negotiables

Violating any of these blocks merge. Each exists because breaking it caused a
real incident or a design-review rejection.

1. **Never edit `src/lib/api/schema.d.ts`.** It is generated from the live
   OpenAPI spec (`make generate-api-types`, requires backend on `:8000`).
   Contract changes flow backend → codegen → typed calls.
2. **All authenticated requests go through `authed()`** (`lib/api/client.ts`);
   public ones use `unwrap()`. The wrapper implements single-flight silent
   refresh + single replay on 401. Hand-rolling token logic is how session
   restore breaks (it did — see §9.2).
3. **Server state via TanStack Query with keys from `keys.ts`.** Never inline
   key arrays at call sites; never mirror server data into `useState`; never
   fetch in effects.
4. **Every data view implements four states**: loading skeleton / empty /
   error+retry / content (plan §43). Skeletons over spinners; spinners only
   inside buttons.
5. **UI strings come from `lib/i18n/strings.ts`** — typed dict, Russian today,
   i18n-ready tomorrow. No literals in JSX. Terminology is locked (SG §51–53):
   «Медицинская карта», «Извлечённая информация»; the word "AI" is banned in
   user-facing copy.
6. **No raw colors/sizes in components.** Use Tailwind utilities mapped to
   `tokens.css` (`bg-primary-soft`, `text-ink-muted`, `rounded-xl`,
   `shadow-[var(--shadow-floating)]`). If you need a new value, add a token
   first and say why in the PR.
7. **WCAG AA beats the style-guide hex values** when they conflict (documented:
   `--color-ink-muted` is darker than SG §5 for 4.5:1 contrast). Semantic
   status is never color-alone — icon or text always accompanies it (SG §6).
8. **Motion is state-driven only**, 150–200 ms ease-out (overlays ≤250 ms).
   No decorative animation; honor `prefers-reduced-motion` (global guard
   already installed).
9. **The backend authorizes; the frontend only hides.** Hiding a button is UX;
   never trust it as security. Handle 401/403/404 gracefully per
   `lib/api/errors.ts`.
10. **No PHI or tokens in logs, toasts, console, or analytics.** Error
    boundaries deliberately swallow route-error details. `console.*` in committed
    code fails review.

---

## 4. Working with the API layer

### Adding/changed endpoint checklist

```bash
# 0. Backend route merged & running on :8000
make generate-api-types     # regenerates src/lib/api/schema.d.ts (commit it)
```

Then, in the owning feature:

1. Add a function in `features/<domain>/api.ts`:

```ts
export function getWidget(id: string) {
  return authed(() =>
    api.GET("/api/v1/widgets/{widget_id}", {
      params: { path: { widget_id: id } },
    }),
  );
}
```

2. Add a hook in `features/<domain>/hooks.ts` using a `keys.*` factory;
   set `enabled:` guards; for moving targets use `refetchInterval` returning
   `false` on terminal states (see `useDocumentWithPolling`).
3. Mutations that change list/detail data must invalidate the affected keys
   in `onSuccess` (see `useUploader`, `useUpdateMyPerson`).
4. Map expected failure codes to ru copy — defaults already exist in
   `errors.ts` (`defaultMessageForStatus`); add overrides only when friendlier
   wording is genuinely needed (e.g. verify-code 400).

### PATCH semantics (important)

Backend treats absent fields as "no change". **Omit empty optional fields from
the payload** so saves never wipe data — see `toPersonUpdate()` in
`features/patients/schemas.ts`. Mirror backend zod-side validators (e.g.
no-future-date-of-birth) for fast feedback, and map 422 `loc[]` field errors
back onto form fields via RHF `setError`.

---

## 5. Styling system

- **Tokens first**: `styles/tokens.css` feeds Tailwind v4 via `@theme`. Colors,
  radii, one floating shadow, motion easing. Need a new visual constant? Token
  it, then use it.
- **Primitives recipe** (`components/ui/*.tsx`) — follow `button.tsx` exactly:

```tsx
export const Widget = forwardRef<HTMLDivElement, ComponentProps<"div">>(
  function Widget({ className, ...props }, ref) {
    return <div ref={ref} data-slot="widget" className={cn("…tokens…", className)} {...props} />;
  },
);
```

  - `forwardRef` is **mandatory** — React 18 silently drops `ref` props on
    plain function components, which breaks `react-hook-form` `register()`
    everywhere an input is involved (this shipped broken once; §9.1).
  - `data-slot="…"` attribute for stable test styling hooks.
  - Variants via `cva`; if exporting both component and variants object, add
    the `react-refresh/only-export-components` disable comment (existing
    examples show placement).
- **Layout grammar** (SG): mobile-first; content column capped ~720 px; bottom
  nav <lg, quiet sidebar ≥lg; cards separated by border, shadow reserved for
  overlays; primary touch targets h-11/h-12, secondary chips ≥h-10.
- **Forms**: RHF + `zodResolver`; label↔input via explicit `htmlFor`/`id`;
  errors render with `role="alert"`; submit buttons disable while pending with
  a text swap («Сохраняем…»), not a spinner overlay.

---

## 6. Testing expectations

| Change type | Required tests |
|---|---|
| Pure logic (reducer, parser, formatter, schema) | Unit tests colocated `*.test.ts` — exhaustive transitions/edges |
| Interactive component (form, input, chip) | Testing Library test: render → interact → assert observable behavior |
| New page or changed user flow | Update/extend E2E; **add the path to the axe+overflow sweep array** in `happy-path.spec.ts` |
| Visual/token tweak | Verify axe scan still passes locally (`make test-e2e`) |

Conventions:

- Unit tests import nothing network-y; mock `fetch` explicitly where needed
  (see `session.test.ts` for the single-flight pattern).
- Component tests use real UI primitives (they're cheap), `userEvent`, and
  assert accessible names/roles — same queries users' assistive tech uses.
- E2E conventions live in `WEB_GUIDE_E2E_TEST.md` §10 (unique identities, RU
  matchers from `strings.ts`, mobile viewport declarations, no PHI logging).

Run everything before pushing:

```bash
make lint-web && make test-web && make build-web   # and test-e2e when relevant
```

---

## 7. Commits & pull requests

- Conventional Commits, scoped: `feat(web): …`, `fix(web): …`,
  `docs(web): …`, `chore(web): …`, plus unscoped `feat(api): …` for backend
  changes. Imperative mood, body explains *why* when not obvious.
- One logical change per commit; milestone work lands as code-commit +
  separate docs-sync commit (see git history for calibration).
- Never commit: `test-results/`, `playwright-report/` (gitignored),
  `.env` values, real patient documents/fixtures with real data.
- PR description: what & why, screenshots/GIF for visual changes, risk notes,
  and which DoD boxes moved in `IMPLEMENTATION_PLAN.md`.

### PR Definition of Done

- [ ] `lint` clean, `vitest` green, `build` green (+ E2E when flows touched)
- [ ] New/changed UI: four states implemented; 320 px OK; keyboard-navigable;
      axe-clean; strings in `strings.ts`
- [ ] Contract change? `schema.d.ts` regenerated in the same PR
- [ ] Milestone work: checkboxes/status updated in `IMPLEMENTATION_PLAN.md`
- [ ] No secrets, no PHI, no stray files (check `git status` before pushing)

---

## 8. Adding a feature — skeleton

```
src/features/widgets/
├── api.ts          # typed calls (authed/unwrap)
├── hooks.ts        # useX queries/mutations, keys.*, invalidation
├── schemas.ts      # zod forms mirroring backend rules
└── components/
    └── WidgetCard.tsx
src/app/auth/WidgetsPage.tsx   # thin composition + route in router.tsx
```

Route registration: add a lazy child under the `(auth)` branch in
`app/router.tsx`; nav item goes into `NAV_ITEMS` in `app/auth/layout.tsx`
(bottom nav is capped at 4 items — extend thoughtfully); add the page to the
E2E sweep paths.

---

## 9. Common pitfalls (learned the hard way)

1. **Unstyled app after touching `main.tsx`** — the
   `import "@/styles/globals.css"` line is load-bearing. Losing it emits zero
   CSS: no breakpoints, both navs visible, dead tokens. E2E catches it; don't
   re-learn it.
2. **Silent refresh asymmetry** — every new protected call must use
   `authed()`. `getMe()` once used bare `unwrap()`: cold reload replayed
   `/patients/me` after refresh but never `/auth/me`. Diagnosed only via
   network-level E2E logging.
3. **React 18 drops `ref` on plain function components** — symptom appears
   far away: RHF validation fails with Zod's misleading *"expected string,
   received undefined"* because the input's ref never registered. Always
   `forwardRef` primitives.
4. **`aria-hidden` skeletons are invisible to role/text queries** — an E2E
   snapshot may show an "empty" panel that is merely loading. Assert the
   post-load state with a raised timeout instead of debugging a ghost.
5. **Backend derives document titles from filename stems** when `title` is
   empty — E2E matchers should not include the extension.
6. **OTP rate limit is 1/min per identity** — E2E logins mint unique
   addresses; manual curl loops against one address will 429.
7. **Duplicate accessible labels break strict-mode locators** (two `<nav>`
   with identical `aria-label` bit us). Keep landmark labels unique by design.
8. **Long min-content text + fixed-width button overflows 320px by pixels** —
   wrap header rows (`flex-wrap` + `min-w-0`), then let the sweep prove it.
9. **`import.meta.env` typing** — needs `/// <reference types="vite/client" />`
   somewhere in scope (or avoid env access outside `lib/`).
10. **Backend refuses placeholder secrets only in production mode** — local/
    CI dev creds (`pdf123`, `ci-…`) produce warnings, not crashes. Don't
    "fix" the warnings by weakening `_security_issues()`.

---

## 10. Questions?

- Architecture intent → `IMPLEMENTATION_PLAN.md` §3–§5
- Visual/UX rulings → `OAI_STYLE_GUIDE.md` (+ deviations logged in `tokens.css`)
- E2E mechanics → `WEB_GUIDE_E2E_TEST.md`
- Backend contract → `apps/account-api/docs/api/*` or just read the OpenAPI
  at `http://localhost:8000/openapi.json`
