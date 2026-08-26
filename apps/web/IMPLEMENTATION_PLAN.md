# Frontend Implementation Plan — MVP-1 (Client Portal)

> **Working document.** Track progress via checkboxes and status labels.
> Companion documents: `OAI_IMPL_PLAN.md` (original architecture vision), `OAI_STYLE_GUIDE.md` (visual system v1.0).

**Legend:** ☐ = not started · ◐ = in progress · ☑ = done · ⛔ = blocked · Status column updated as work progresses.

---

## 0. Decisions Log

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | Framework | **Vite + React Router (keep)** | Private SPA, no SSR/SEO need; existing code + CORS (`:5173`) already wired |
| D2 | Token storage | **access in memory + refresh in `localStorage["ddp.refresh"]`** | No backend cookie endpoints exist; silent refresh on 401; harden post-MVP |
| D3 | Scope | **MVP-1 only** | Auth + Dashboard + Upload + Document status + Record + Extracted data |
| D4 | Auth model | **OTP only** | Backend has no passwords; register == first login (auto-creates account) |
| D5 | Upload transport | **Multipart through FastAPI** | Presigned browser PUT does not exist server-side yet |
| D6 | Realtime | **Polling (4s)** while document is non-terminal | Plan §23: WebSocket deferred |
| D7 | UI language | **Russian strings via i18n-ready strings module** | Style guide §51–52; no framework, plain typed dict |
| D8 | Dark mode | **Not built**; tokens structured for later | Style guide §8 |
| D9 | PDF viewing | Native `<object>`/image render first; react-pdf later | Bundle size; lazy-load when needed |

---

## 1. Backend Reality Alignment (constraints we build against)

Actual backend surface (verified against `apps/account-api`, base `/api/v1`):

| Endpoint | Method | Notes for frontend |
|---|---|---|
| `/auth/request-otp` | POST `{identity}` | 202; rate limit **1/min per identity** → cooldown timer |
| `/auth/verify` | POST `{identity, code}` | Returns `{access_token, refresh_token}`; auto-creates account |
| `/auth/refresh` | POST `{refresh_token}` | Rotates refresh token; old one revoked |
| `/auth/logout` | POST `{refresh_token}` | 204 |
| `/auth/me` | GET | Bearer; `{id,email,phone,status,is_subscribed}` — **no roles field** (ticket BK-1) |
| `/patients/me` | GET/PATCH | Auto-creates patient profile on first GET |
| `/patients/{pid}/documents` | **GET list** · POST multipart | GET returns newest-first `DocumentResponse[]` (added in BK-7, commit f840ff2). POST fields: `upload`, `document_type`, `title`, `encounter_id?`; limits: pdf/jpeg/png/tiff, ≤50MB, quota 10 (free) → map 413/415/429 |
| `/documents/{id}` | GET | `status`: pending → processing → completed/failed (workers currently stubs → may stay `processing`) |
| `/documents/{id}/versions` | GET | Version list |
| `/documents/{id}/extractions` | GET | Extracted data (empty until AI worker exists) |
| `/documents/{id}/download` | GET | `{download_url, expires_in:900}` presigned S3 |

Datetime responses are converted to **Europe/Moscow (+03:00)** server-side — display as-is, format client-side for ru locale.

⛔ Known backend gaps (file tickets, do **not** work around in frontend):
- [ ] **BK-1** `/auth/me` must include `roles[]` (required before specialist portal)
- [ ] **BK-2** Timeline endpoint `GET /patients/{pid}/timeline`
- [ ] **BK-3** Analytics endpoints
- [ ] **BK-4** `DELETE /documents/{id}`
- [ ] **BK-5** Post-MVP security: HttpOnly cookie session option
- [ ] **BK-6** marker-worker / ai-worker stubs — documents stuck in `processing`; UI must show honest "Обработка" state indefinitely
- [x] **BK-7** ~~Document listing endpoint~~ → **resolved**: `GET /patients/{pid}/documents` added (commit f840ff2)

---

## 2. Tech Stack (final)

| Layer | Choice | Install task |
|---|---|---|
| Build / routing | Vite 5 + React Router 6 *(existing)* | — |
| Styling | Tailwind CSS + shadcn/ui | `tailwindcss`, `shadcn@latest init` |
| Server state | TanStack Query v5 | `@tanstack/react-query` |
| Forms / validation | React Hook Form + Zod | `react-hook-form`, `zod`, `@hookform/resolvers` |
| API typing | openapi-typescript + openapi-fetch | codegen script from `localhost:8000/openapi.json` |
| Icons | lucide-react (stroke 2px; 16/20/24px only) | |
| Toasts | sonner | |
| Tests | Vitest + Testing Library + Playwright | |
| Lint/format | ESLint + Prettier | |

Package manager: **npm** (pnpm workspace deferred to mobile-prep phase).

---

## 3. Target Directory Structure

```
apps/web/src/
├── app/                              # thin route files ONLY
│   ├── router.tsx                    # guards, lazy routes
│   ├── public/
│   │   ├── LoginPage.tsx
│   │   └── VerifyPage.tsx
│   └── auth/                         # guarded layout + pages
│       ├── layout.tsx                # AppShell (bottom nav / sidebar)
│       ├── DashboardPage.tsx
│       ├── DocumentsPage.tsx
│       ├── DocumentDetailPage.tsx
│       ├── MedicalRecordPage.tsx
│       └── ProfilePage.tsx
├── features/
│   ├── auth/
│   │   ├── api.ts                    # requestOtp, verify, refresh, logout, me
│   │   ├── hooks.ts                  # useMe, useLogin mutations
│   │   ├── schemas.ts                # zod: identity, otp
│   │   ├── session.ts                # token store (memory + localStorage), single-flight refresh
│   │   └── components/
│   │       ├── IdentityForm.tsx      # email|phone smart field
│   │       ├── OtpInput.tsx          # 6 cells, auto-advance, paste, resend cooldown
│   │       └── LogoutButton.tsx
│   ├── patients/
│   │   ├── api.ts                    # getMyPatient, patchMyPatient
│   │   └── hooks.ts
│   ├── documents/
│   │   ├── api.ts                    # upload(multipart XHR), getDocument, versions, extractions, downloadUrl
│   │   ├── uploadMachine.ts          # pure reducer state machine (unit-tested)
│   │   ├── hooks.ts                  # useDocuments, useDocument(polling), useUploader
│   │   └── components/
│   │       ├── Uploader.tsx          # mobile action-sheet / desktop dropzone (SG §42–43)
│   │       ├── DocumentList.tsx      # grouped by month (SG §56)
│   │       ├── DocumentCard.tsx      # SG §17 minimal variant
│   │       ├── ProcessingStatus.tsx  # Uploaded→Processing→Ready→Needs attention (SG §31)
│   │       ├── ExtractionViewer.tsx  # SG §35, §38: name/value/unit/reference cards
│   │       └── OriginalViewer.tsx    # lazy <object>/img (D9)
│   └── medical-record/
│       └── components/
│           ├── RecordTabs.tsx
│           └── OverviewTab.tsx
├── components/ui/                    # shadcn primitives (curated list below)
├── lib/
│   ├── api/
│   │   ├── client.ts                 # openapi-fetch instance; auth header; 401 refresh queue
│   │   ├── errors.ts                 # ApiError + status mapping table
│   │   └── schema.d.ts               # GENERATED — never edit by hand
│   ├── query/keys.ts                 # central query keys factory
│   ├── i18n/strings.ts               # ru dict, typed; en slot later (D7)
│   └── utils/format.ts               # dates (ru locale), bytes, mime→label
├── styles/
│   ├── globals.css
│   └── tokens.css                    # SG §55 design tokens (source of truth)
├── main.tsx
└── App.tsx                           # providers only (QueryClient, Toaster)
```

---

## 4. Design System (from OAI_STYLE_GUIDE.md → tokens)

All values below become CSS custom properties in `styles/tokens.css` and are mapped into the Tailwind theme. **Components must never hardcode colors** (SG §55).

### 4.1 Tokens checklist

- [x] Colors — Background `#F8F9F7`, Surface `#FFFFFF`, Surface muted `#F1F3F0`
- [x] Colors — Primary `#557A72`, Primary dark `#3F625B`, Primary soft `#E8F0EE`
- [x] Text — `#202522` / secondary `#626B65` / muted `#8A928C` / disabled `#B5BBB7` (no pure black)
- [x] Borders — `#E2E6E2`, strong `#D1D7D2`, input `#D9DEDA`
- [x] Semantic — success `#4F7A63`/bg `#EAF2EC`; warning `#9A7842`/bg `#F7F1E5`; error `#9A5A56`/bg `#F7EAEA`; info `#58718A`/bg `#EAF0F4`
- [x] Typography — Inter/system sans; weights 400/500/600 only; scale Display 36 → Caption 12 (mobile H1 28/H2 22/H3 18)
- [x] Spacing — 4px base scale (4…80); label→input 8, input→input 16, section 40
- [x] Radius — sm 6, default 10, lg 14, modal 16; buttons 8, cards 12
- [x] Shadows — none by default; one floating shadow token `0 8px 30px rgba(...)` for modal/popover/sheet only
- [x] Motion — 150–200ms ease-out (drawer/modal 200–250ms); state-driven only; honor `prefers-reduced-motion`
- [x] Color ratio guardrail — ~70% neutral / 20% text+border / 8% accent / 2% semantic

### 4.2 shadcn primitives to install/configure

- [x] button (primary 44px/48px mobile, h-11; secondary bordered; tertiary text-button; destructive lives inside menu + confirm dialog, never red primary — SG §21–24)
- [x] input / label *(textarea / select / radio-group / checkbox — added when screens need them)*
- [x] card (border-separated, no shadow — SG §15/§17)
- [x] badge (status chips; icon/text always paired with color — SG §6)
- [x] skeleton (content loading; spinners only inline micro-actions — SG §48)
- [ ] tabs / drawer(bottom sheet) / dropdown-menu / progress *(M5–M6)* · alert / avatar / separator*(separator done)*
- [x] toaster (sonner; sparse usage — SG §49)

### 4.3 Terminology (locked, SG §51–53)

| EN concept | RU UI string |
|---|---|
| Documents | Документы |
| Medical record | Медицинская карта |
| Specialist | Специалист |
| Encounter | Приём |
| Lab result | Результат лабораторного исследования |
| Extracted information | Извлечённая информация |
| Processing status set | Загружен · Обрабатывается · Готов · Требует внимания |

Banned in UI: "AI", "AI Insights", "Smart Analytics" → use "Извлечённая информация", "Последние результаты".

---

## 5. Architecture Specifications

### 5.1 Session & auth flow

```
/login  IdentityForm → POST /auth/request-otp {identity}        [202] → /login/verify
/login/verify  OtpInput → POST /auth/verify {identity, code}    [200 tokens]
  → access_token: memory singleton (module-scoped variable)
  → refresh_token: localStorage["ddp.refresh"]
  → bootstrap: parallel GET /auth/me + GET /patients/me → redirect /
/logout → POST /auth/logout {refresh_token} → wipe → /login
```

- [x] Single-flight refresh: first 401 triggers `POST /auth/refresh`; concurrent requests await same promise; original request replayed once
- [x] Refresh failure (400/401) → wipe storage → hard redirect `/login`
- [ ] Optional proactive refresh at JWT `exp − 60s` (deferred — silent refresh on first call covers reload case)
- [x] Route guards: `(public)` redirects to `/` if session valid; `app/*` requires valid session else `/login`
- [x] Resend-OTP cooldown: 60s countdown (matches backend rate limit), disable button, show remaining seconds

### 5.2 Upload state machine (`uploadMachine.ts` — pure reducer)

```
IDLE → VALIDATING → UPLOADING → QUEUED → POLLING → COMPLETED
                         ↓            ↘ FAILED ← (terminal doc status failed)
                       ERROR ⇄ RETRY(↺ UPLOADING)   CANCELLED
```

- [ ] Client-side validation (UX only): mime ∈ {application/pdf, image/jpeg, image/png, image/tiff}; size ≤ 50 MB; friendly ru error messages
- [ ] Transport: XHR `POST /patients/{pid}/documents` multipart — `upload.onprogress` %, `xhr.abort()` cancel
- [x] Polling: TanStack Query `refetchInterval: 4000` on `["document", id]` while `status ∈ {pending, processing}`; stops automatically on terminal status *(implemented in M3 — `useDocumentWithPolling`)*
- [ ] After QUEUED success: invalidate `["documents", pid]` + toast «Документ загружен»
- [ ] Map backend errors: 413 «Файл слишком большой», 415 «Неподдерживаемый тип файла», 429 «Достигнут лимит документов» (free tier = 10)
- [ ] Honest processing state: if stuck in Обрабатывается > N min, show calm hint text (workers are stubs today — BK-6)

### 5.3 Query keys (`lib/query/keys.ts`)

```ts
keys.me()                        // ["me"]
keys.patientMe()                 // ["patient","me"]
keys.documents(pid)              // ["documents", pid]
keys.document(id)                // ["document", id]
keys.versions(id)                // ["document", id, "versions"]
keys.extractions(id)             // ["document", id, "extractions"]
```

Invalidation rules:
- [ ] Upload confirm → invalidate `documents(pid)`
- [ ] Profile PATCH → invalidate `patientMe()`

### 5.4 Error handling (`lib/api/errors.ts`)

- [x] `ApiError {status, detail, fields?}` parsed from FastAPI `{detail}` shape (incl. 422 `loc` mapping to form fields) *(M1, unit-tested)*
- [x] Global behavior matrix implemented in `errors.ts` defaults + client retry; per-screen application ongoing (403 inline / 404 page states land with M5–M6 screens)
- [x] Every data screen implements all four states: loading skeleton / empty / error+retry / content (plan §43) — dashboard done; carried per-screen for the rest
- [x] Empty state (documents): «Пока нет документов. Загрузите первый медицинский документ…» + CTA — small line icon only (SG §30)

---

## 6. Screens (MVP-1) — build order & acceptance criteria

Style guide refs in brackets. Each screen must pass: mobile 320px ✓, keyboard nav ✓, all four states ✓, ru strings module ✓.

### 6.1 Login `/login`
- [x] Smart identity field (accepts email or phone, zod validation) [SG §25–26 forms: no giant card]
- [x] Submit → request OTP → navigate verify; 422/429 handling
- [x] Calm privacy line: «Ваши документы приватны» [SG §50]

### 6.2 Verify `/login/verify`
- [x] 6-cell OTP input: auto-advance, backspace, paste-full-code support
- [x] Resend with 60s cooldown; change-identity link back
- [x] On success: store tokens → bootstrap me/patient → `/dashboard`

### 6.3 AppShell (guarded layout)
- [x] Mobile: bottom navigation, max 4 items — Главная · Карта · Документы · Профиль [SG §27]
- [x] Desktop ≥lg: quiet left sidebar, active item = soft bg `#E8F0EE` + dark green text [SG §28–29]
- [x] Content centered, generous whitespace, page width cap ~720px for reading screens [SG §58]

### 6.4 Dashboard `/`
- [x] Greeting by time of day + first_name (fallback neutral)
- [x] Medical record summary card → link to карта [SG §2: record > metrics]
- [x] Recent documents (last 5, DocumentCard reuse)
- [x] Primary CTA «Загрузить документ» → navigates /documents until M4 wires Uploader
- [x] NO metric tiles / counters row [SG §2 anti-pattern]

### 6.5 Documents `/documents`
- [ ] Header + «+ Добавить» [SG §42]
- [ ] Mobile: Add → bottom sheet [Сделать фото] [Выбрать файл] [Отмена]; desktop: button + drag&drop dropzone [SG §42–43]
- [ ] List grouped by month («Август 2026») [SG §56]; DocumentCard: type tag (PDF/Image), title, date ru-format, status chip + chevron [SG §17–18]
- [ ] Type filter chips: Все · Лаборатория · Приёмы · Другое (client-side for MVP)
- [ ] Skeleton cards while loading; empty state per SG §30
- [ ] Card click → `/documents/:id`

### 6.6 Document detail `/documents/:id`
- [ ] Header: type tag, title, date; overflow ••• menu (Download; Delete disabled until BK-4)
- [ ] Processing stepper: Загружен → Обрабатывается (slow dots animation, SG §32) → Готов | Требует внимания [SG §31]; polling per 5.2
- [ ] Tabs: Оригинал | Извлечённая информация
  - [ ] Оригинал: lazy `<object>` PDF / `<img>` for images [D9]; «Открыть документ» fallback on mobile [SG §40]
  - [ ] Извлечённая информация: value cards — name / value+unit / Reference range or «Референсный диапазон недоступен» [SG §35]; within/above/below provided range wording only [SG §36]; mobile stacked cards, desktop optional table [SG §38]; empty state «Информация ещё извлекается»
- [ ] Download action: `GET /download` → open `download_url` new tab

### 6.7 Medical record `/medical-record`
- [ ] Tabs: Обзор | Документы (reuse DocumentList filtered)
- [ ] Overview: person data read-only (name, DOB, sex) + privacy line; «Изменить в профиле» link
- [ ] Read-only for MVP

### 6.8 Profile `/profile`
- [ ] RHF+zod form: имя, фамилия, отчество, дата рождения, пол → PATCH `/patients/me` → invalidate → toast «Изменения сохранены» [SG §49]
- [ ] Account block: email/phone (read-only), subscription status
- [ ] Logout button (tertiary placement, confirm not required)

---

## 7. Milestones & Task Tracking

> Update Status column: `Planned / In progress / Done / Blocked`. Checkboxes mirror granular completion.

### M0 — Bootstrap
| Task | Done | Status |
|---|---|---|
| Install deps: tailwind, tanstack-query, rhf, zod, lucide, sonner, openapi-typescript, openapi-fetch, vitest, rtl | ☑ | Done |
| shadcn-style primitives + tokens.css mapped into tailwind theme (§4.1 all boxes) | ☑ | Done |
| ESLint + Prettier config; scripts: `lint`, `format`, `test`, `test:e2e`, `generate:api` | ☑ | Done |
| `generate:api` script: fetch openapi.json → schema.d.ts (committed) | ☑ | Done |
| Providers wiring in App.tsx (QueryClient, Toaster); router scaffold with route tree | ☑ | Done |

### M1 — API layer
| Task | Done | Status |
|---|---|---|
| lib/api/client.ts: base client, auth header injection, credentials mode | ☑ | Done |
| Session module: memory access token, localStorage refresh, single-flight refresh, logout wipe | ☑ | Done |
| ApiError class + status mapping matrix | ☑ | Done |
| features/auth/api.ts + patients/documents api modules (typed via generated schema) | ☑ | Done |
| query keys factory | ☑ | Done |
| Unit tests: session refresh logic, ApiError parsing | ☑ | Done |

### M2 — Authentication screens
| Task | Done | Status |
|---|---|---|
| LoginPage + IdentityForm (zod, ru errors) | ☑ | Done |
| VerifyPage + OtpInput (advance/paste/cooldown) | ☑ | Done |
| Guards (public/authenticated), bootstrap loading gate | ☑ | Done |
| Component tests: IdentityForm validation, OtpInput behavior | ☑ | Done |

> Note (M2): React 18 requires `forwardRef` on UI primitives — plain function
> components silently drop the ref that RHF's `register()` passes, which broke
> validation with a misleading Zod "expected string, received undefined".

### M3 — Shell + Dashboard
| Task | Done | Status |
|---|---|---|
| AppShell: bottom nav (mobile) + sidebar (desktop), active states per SG §28–29 | ☑ | Done |
| Dashboard: greeting, record card, recent docs, quick upload CTA | ☑ | Done |
| Skeletons for all dashboard queries | ☑ | Done |
| *(unplanned)* BK-7 backend: `GET /patients/{pid}/documents` + types regen | ☑ | Done |
| *(pulled forward from M4)* DocumentCard + ProcessingStatus components | ☑ | Done |

> Note (M3): dashboard "Recent documents" required a document listing endpoint
> that did not exist — resolved by wiring the already-present
> `DocumentService.list_documents()` to an HTTP route (BK-7).

### M4 — Documents core (vertical slice heart)
| Task | Done | Status |
|---|---|---|
| uploadMachine reducer + unit tests (all transitions incl. abort/retry) | ☐ | Planned |
| Uploader: mobile action-sheet + desktop dropzone, progress bar, cancel | ☐ | Planned |
| DocumentsPage: month-grouped list, filter chips, empty/error states | ☐ | Planned |
| DocumentCard + ProcessingStatus chip component | ☐ | Planned |
| Upload error mapping (413/415/429) to ru messages | ☐ | Planned |

### M5 — Document detail
| Task | Done | Status |
|---|---|---|
| Detail header + ••• menu + download flow | ☐ | Planned |
| Processing stepper + polling hook | ☐ | Planned |
| OriginalViewer lazy `<object>`/img + mobile fallback | ☐ | Planned |
| ExtractionViewer (value cards, reference handling, empty state) | ☐ | Planned |
| Component tests: ProcessingStatus rendering per status | ☐ | Planned |

### M6 — Record + Profile
| Task | Done | Status |
|---|---|---|
| MedicalRecordPage tabs (Overview read-only + Documents reuse) | ☐ | Planned |
| ProfilePage form → PATCH → invalidation → toast | ☐ | Planned |
| LogoutButton + session cleanup E2E-ready | ☐ | Planned |

### M7 — Hardening & E2E
| Task | Done | Status |
|---|---|---|
| Playwright happy path: login (OTP fetched from redis via docker exec) → dashboard → upload sample.pdf → polling state visible → detail opens | ☐ | Planned |
| Playwright auth isolation: direct doc URL of other patient → graceful 403/404 screen | ☐ | Planned |
| a11y pass (axe): focus states, contrast vs SG palette, semantic buttons (no div onClick), reduced-motion respected | ☐ | Planned |
| Error boundaries per route; console.log cleanup; no PHI in logs/toasts | ☐ | Planned |
| Touch targets ≥44px audit; 320px viewport sweep | ☐ | Planned |

### Milestone summary

| Milestone | Est | Status | Completed on |
|---|---|---|---|
| M0 Bootstrap | 0.5d | **Done** | 2026-08-25 |
| M1 API layer | 1d | **Done** | 2026-08-25 |
| M2 Auth screens | 1–2d | **Done** | 2026-08-26 |
| M3 Shell + Dashboard | 1d | **Done** | 2026-08-26 |
| M4 Documents core | 2–3d | Planned | — |
| M5 Document detail | 1–2d | Planned | — |
| M6 Record + Profile | 1–2d | Planned | — |
| M7 Hardening + E2E | 1–2d | Planned | — |
| **Total** | **~8–12d** | | |

---

## 8. Definition of Done — MVP-1

- [ ] Full flow works against local docker compose stack: login → dashboard → upload real PDF → status transitions → detail view → download
- [ ] All screens implement 4 UI states and pass 320px/keyboard/a11y checks
- [ ] Visual output matches style guide tokens (spot-check against SG §56 density level)
- [ ] `npm run lint && npm test` green; Playwright suite green
- [ ] No secrets/PHI in logs; no tokens outside memory/localStorage-approved key

## 9. Explicit Non-Goals (MVP-1)

Presigned browser uploads · WebSocket/SSE · timeline/analytics/specialist/admin portals · PWA/offline · i18n framework (strings module only) · role-based routing · document deletion (no endpoint) · password flows · dark mode.
