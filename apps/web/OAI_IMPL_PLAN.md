Да. Ниже я бы зафиксировал **полный frontend implementation plan** для вашего проекта на **Next.js + React + TypeScript**, с учётом уже определённой backend-архитектуры: FastAPI Account API, S3, RabbitMQ, отдельный ephemeral Marker GPU worker, AI worker, PostgreSQL/Qdrant, client/specialist/admin и электронная медицинская карта.

Я сознательно рассматриваю frontend как отдельное приложение, которое взаимодействует с FastAPI через API, а не как часть backend.

---

# 1. Целевая frontend-архитектура

Итоговая система:

```text
                         ┌──────────────────────┐
                         │      User Browser    │
                         │                      │
                         │   Next.js + React    │
                         │   TypeScript         │
                         └──────────┬───────────┘
                                    │
                              HTTPS / JSON
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │      FastAPI         │
                         │     Account API      │
                         └──────────┬───────────┘
                                    │
             ┌──────────────────────┼──────────────────────┐
             │                      │                      │
             ▼                      ▼                      ▼
        PostgreSQL                  S3                 RabbitMQ
                                    ▲
                                    │
                              direct upload
                                    │
                              Browser ────────┘
```

Дальше backend pipeline:

```text
RabbitMQ
    │
    ▼
Marker Orchestrator
    │
    ├── start GPU VPS
    │
    ▼
Marker Worker
    │
    ▼
S3
    │
    ▼
AI Worker
    │
    ├── PostgreSQL
    └── Qdrant
```

Frontend **не должен знать о Marker, RabbitMQ, Qdrant или внутренних worker'ах**.

Для frontend backend выглядит примерно так:

```text
Authentication API
Patient API
Medical Record API
Document API
Encounter API
Access API
Analytics API
```

---

# 2. Главные frontend-принципы

Я бы зафиксировал их до начала разработки.

### 1. Next.js отвечает за web UI

```text
Next.js
 ├── routing
 ├── rendering
 ├── layouts
 ├── SEO where needed
 └── React components
```

### 2. FastAPI отвечает за business logic

Не переносить медицинскую бизнес-логику в Next.js.

### 3. Browser загружает файлы непосредственно в S3

```text
Browser
   │
   ├── init upload → FastAPI
   │
   ├── upload → S3
   │
   └── confirm → FastAPI
```

### 4. Frontend получает только разрешённые данные

Frontend не должен пытаться самостоятельно решать:

```text
"может ли specialist видеть patient?"
```

Он может скрыть кнопку, но **authorization всегда выполняет backend**.

### 5. Mobile-first

Сначала:

```text
320–430px
```

потом:

```text
tablet
desktop
large desktop
```

### 6. API contracts генерируются из FastAPI OpenAPI

Не дублировать Pydantic schemas вручную в TypeScript.

---

# 3. Структура frontend в monorepo

Я бы добавил frontend в существующий monorepo следующим образом:

```text
medical-platform/
│
├── apps/
│   │
│   ├── account-api/
│   │
│   ├── marker-worker/
│   │
│   ├── marker-orchestrator/
│   │
│   ├── ai-worker/
│   │
│   └── web/
│       ├── public/
│       ├── src/
│       ├── tests/
│       ├── package.json
│       ├── next.config.ts
│       ├── tsconfig.json
│       └── ...
│
├── packages/
│   ├── api-client/
│   ├── contracts/
│   ├── validation/
│   └── config/
│
├── docs/
│
└── package.json
```

Позже:

```text
apps/
├── web/
└── mobile/
```

где `mobile` будет Expo.

---

# 4. Frontend stack

Я бы зафиксировал:

```text
Next.js
React
TypeScript

Tailwind CSS
shadcn/ui

TanStack Query
React Hook Form
Zod

Recharts

Lucide Icons

Vitest
React Testing Library
Playwright
```

Для package manager:

```text
pnpm
```

и workspace:

```text
pnpm-workspace.yaml
```

---

# 5. Почему не Redux

На старте Redux не нужен.

Разделить state на три категории.

## Server state

```text
patients
documents
medical records
analytics
encounters
access grants
```

→ **TanStack Query**

## Form state

```text
login
registration
profile
encounter
upload
access grant
```

→ **React Hook Form**

## Local UI state

```text
modal opened
sidebar opened
selected tab
filters
```

→ `useState` / `useReducer`.

Это значительно проще.

---

# 6. Проектирование маршрутов

Я бы сразу проектировал routing вокруг ролей.

```text
/
├── login
├── register
├── forgot-password
│
├── app/
│   ├── dashboard
│   ├── medical-record
│   ├── documents
│   ├── analytics
│   ├── profile
│   └── settings
│
├── specialist/
│   ├── dashboard
│   ├── patients
│   ├── patients/[patientId]
│   ├── patients/[patientId]/record
│   ├── patients/[patientId]/documents
│   ├── patients/[patientId]/encounters
│   └── patients/[patientId]/analytics
│
└── admin/
    ├── dashboard
    ├── users
    ├── organizations
    └── audit
```

Но физически Next.js App Router можно организовать иначе.

Я бы сделал:

```text
src/app/

├── (public)/
│   ├── page.tsx
│   ├── login/
│   └── register/
│
├── (authenticated)/
│   ├── layout.tsx
│   ├── dashboard/
│   ├── medical-record/
│   ├── documents/
│   ├── analytics/
│   └── profile/
│
├── specialist/
│   ├── layout.tsx
│   ├── dashboard/
│   ├── patients/
│   └── patients/[patientId]/
│
└── admin/
    └── ...
```

---

# 7. Root layout

Root layout отвечает только за глобальную инфраструктуру:

```text
RootLayout
│
├── ThemeProvider
├── QueryProvider
├── AuthProvider
├── Toaster
└── Application
```

Не надо помещать сюда медицинские компоненты.

---

# 8. Auth architecture

Это один из первых блоков.

Flow:

```text
Register
    ↓
Verify email/phone
    ↓
Login
    ↓
Authenticated session
    ↓
GET /me
    ↓
Determine role
    ↓
Redirect
```

Например:

```text
CLIENT
    ↓
/app/dashboard

SPECIALIST
    ↓
/specialist/dashboard

ADMIN
    ↓
/admin/dashboard
```

---

# 9. Authentication state

Frontend должен иметь:

```typescript
type CurrentUser = {
  id: string;
  role: Role;
  person: Person;
  patient?: Patient;
  specialist?: Specialist;
};
```

Но не хранить критичные данные в localStorage.

Предпочтительно:

```text
HttpOnly Secure Cookie
```

Frontend:

```text
GET /me
```

получает текущего пользователя.

---

# 10. Auth route protection

Нужно два уровня.

### UI protection

Например specialist routes:

```text
/specialist/*
```

доступны только specialist.

### Backend protection

Даже если пользователь вручную вызовет:

```text
GET /patients/123
```

backend должен проверить permission.

Frontend protection — UX.

Backend protection — security.

---

# 11. Feature-based architecture

Главная структура:

```text
src/
├── app/
│
├── features/
│   ├── auth/
│   ├── patients/
│   ├── medical-record/
│   ├── documents/
│   ├── encounters/
│   ├── analytics/
│   ├── specialist-access/
│   └── profile/
│
├── components/
│   ├── ui/
│   ├── layout/
│   └── feedback/
│
├── lib/
│   ├── api/
│   ├── auth/
│   ├── query/
│   ├── storage/
│   └── utils/
│
├── hooks/
│
├── types/
│
└── styles/
```

---

# 12. `features/auth`

```text
features/auth/
├── api/
│   ├── login.ts
│   ├── register.ts
│   ├── logout.ts
│   └── get-current-user.ts
│
├── components/
│   ├── LoginForm.tsx
│   ├── RegisterForm.tsx
│   ├── LogoutButton.tsx
│   └── VerificationForm.tsx
│
├── hooks/
│   ├── useCurrentUser.ts
│   └── useLogin.ts
│
├── schemas/
│   ├── login.schema.ts
│   └── register.schema.ts
│
└── types.ts
```

---

# 13. Registration UX

Поскольку регистрация возможна через email или phone, интерфейс:

```text
Create account

○ Email
○ Phone

Email
[________________]

Password
[________________]

Confirm password
[________________]

[ Create account ]
```

Позже verification:

```text
Enter verification code

[ _ ][ _ ][ _ ][ _ ][ _ ][ _ ]
```

Не надо сразу делать сложный multi-step registration.

---

# 14. Dashboard клиента

Первый полноценный экран после login.

```text
Good morning, Anna

┌─────────────────────────┐
│ Medical Record          │
│ Last updated today      │
│                         │
│ [ Open record ]         │
└─────────────────────────┘

Recent documents

Blood test
15 Aug 2026
Processing complete

Cardiologist report
10 Aug 2026
Processing...
```

На mobile — cards.

На desktop — grid.

---

# 15. Medical Record — центральная feature

Не делать его просто списком документов.

Структура:

```text
Medical Record
│
├── Overview
├── Timeline
├── Documents
├── Lab Results
├── Diagnoses
├── Medications
└── Analytics
```

Frontend components:

```text
features/medical-record/
├── components/
│   ├── MedicalRecordHeader.tsx
│   ├── MedicalRecordSummary.tsx
│   ├── MedicalTimeline.tsx
│   ├── MedicalEvent.tsx
│   ├── ObservationCard.tsx
│   └── RecordTabs.tsx
```

---

# 16. Timeline

Один из главных компонентов приложения.

```text
August 2026

● 15 Aug
  Cardiologist consultation

● 14 Aug
  Blood test

● 12 Aug
  Prescription

July 2026

● 20 Jul
  General practitioner
```

API:

```text
GET /patients/{patientId}/timeline
```

Frontend не должен самостоятельно объединять 5 разных API endpoints для построения timeline.

Лучше backend отдаёт нормализованный timeline DTO.

---

# 17. Documents feature

```text
features/documents/
├── api/
│   ├── init-upload.ts
│   ├── confirm-upload.ts
│   ├── get-documents.ts
│   ├── get-document.ts
│   └── delete-document.ts
│
├── components/
│   ├── DocumentList.tsx
│   ├── DocumentCard.tsx
│   ├── DocumentUploader.tsx
│   ├── UploadProgress.tsx
│   ├── ProcessingStatus.tsx
│   └── DocumentViewer.tsx
│
├── hooks/
│   ├── useDocuments.ts
│   └── useDocumentUpload.ts
│
└── types.ts
```

---

# 18. Upload workflow

Это необходимо реализовать как отдельный state machine.

```text
SELECTING
    ↓
VALIDATING
    ↓
INITIALIZING
    ↓
UPLOADING
    ↓
CONFIRMING
    ↓
QUEUED
    ↓
PROCESSING
    ↓
COMPLETED
```

Error:

```text
      ┌──── ERROR
      │
UPLOAD
      │
      └──── RETRY
```

---

# 19. Upload component

На mobile:

```text
┌───────────────────────────┐
│ Add document              │
│                           │
│  📷 Take photo            │
│                           │
│  📁 Choose from device    │
│                           │
└───────────────────────────┘
```

На desktop:

```text
┌────────────────────────────────────┐
│                                    │
│    Drop PDF or image here          │
│                                    │
│       or [Choose file]             │
│                                    │
└────────────────────────────────────┘
```

Один component, responsive behavior.

---

# 20. File validation

Frontend проверяет:

```text
file type
file size
file name
```

Например:

```text
application/pdf
image/jpeg
image/png
```

Но backend **обязательно повторяет validation**.

Frontend validation — UX.

Backend validation — security.

---

# 21. S3 upload

Frontend flow:

```typescript
const upload = await initUpload(file);

await fetch(upload.presignedUrl, {
  method: "PUT",
  body: file,
});

await confirmUpload(upload.documentId);
```

Для больших файлов нужен:

```text
progress
abort
retry
```

Позже можно перейти на multipart upload, если понадобится.

---

# 22. Document processing UI

После upload пользователь должен видеть:

```text
Blood-test.pdf

✓ Uploaded
✓ Queued
● Analyzing
○ Completed
```

При ошибке:

```text
Blood-test.pdf

✓ Uploaded
✓ Converted
✕ Analysis failed

[Retry]
```

Frontend получает status через API.

Не подключать WebSocket на первом этапе без необходимости.

Можно:

```text
poll every 3–5 seconds
```

только пока document находится в processing state.

---

# 23. Почему polling сначала лучше

У вас pipeline может занимать:

```text
seconds
minutes
```

WebSocket усложняет:

* infrastructure;
* authentication;
* reconnect;
* scaling.

Для MVP:

```text
GET /documents/{id}
```

polling.

Позже можно добавить SSE/WebSocket, если UX действительно требует realtime.

---

# 24. Document viewer

Нужны:

```text
PDF
JPEG
PNG
Markdown/structured result
```

Я бы разделил:

```text
DocumentViewer
├── PdfViewer
├── ImageViewer
└── ExtractedDataViewer
```

Не смешивать binary document и extracted medical data.

---

# 25. Extracted medical data

Например:

```text
Blood Test

Hemoglobin
135 g/L
Reference: 120–160

Leukocytes
6.2 ×10⁹/L
Reference: 4–10
```

Для каждого результата:

```text
name
value
unit
reference range
date
source document
```

---

# 26. Analytics

Frontend feature:

```text
features/analytics/
├── api/
│   ├── get-observations.ts
│   └── get-trends.ts
│
├── components/
│   ├── MetricCard.tsx
│   ├── ObservationChart.tsx
│   ├── TrendIndicator.tsx
│   └── AnalyticsFilters.tsx
│
└── types.ts
```

---

# 27. Charts должны быть mobile-first

Mobile:

```text
Hemoglobin

140 ┤       ●
135 ┤   ●───┘
130 ┤ ●
    └──────────
     Jan Mar Aug
```

Desktop:

```text
┌──────────────────────────────────────┐
│ Hemoglobin                           │
│                                      │
│ 140 ┤                         ●      │
│ 135 ┤               ●─────────       │
│ 130 ┤       ●───────                 │
│     └────────────────────────────    │
└──────────────────────────────────────┘
```

---

# 28. Specialist application

Это фактически отдельный product area внутри того же Next.js application.

```text
features/specialist/
├── patients/
├── patient-record/
├── encounters/
├── access/
└── analytics/
```

---

# 29. Specialist dashboard

```text
Good morning, Dr. Smith

Patients
128

Recent activity
────────────────────
Anna Smith       15 Aug
John Doe         14 Aug
...

[ Patients ]
```

---

# 30. Patient search

Specialist должен иметь:

```text
Search patients
[_____________________]

Filters

Name
Status
Last visit
```

Backend:

```text
GET /specialist/patients?search=...
```

Не загружать всех пациентов в browser.

---

# 31. Patient profile specialist view

```text
Patient
Anna Smith
DOB: ...

[Overview] [Record] [Documents] [Encounters] [Analytics]
```

Важно:

Frontend должен показывать только те actions, которые backend разрешает.

Например:

```text
can_view_documents
can_upload_documents
can_view_analytics
can_edit_encounters
```

---

# 32. Access management

Специалист:

```text
Request access
```

или пациент:

```text
Grant access to specialist
```

UX:

```text
Dr. Smith

Access:
✓ Medical record
✓ Documents
✓ Analytics

Expires:
[ 30 Sep 2026 ]

[Grant access]
```

Backend всё равно проверяет AccessGrant.

---

# 33. Encounter creation

Specialist после приёма:

```text
New encounter

Date
[ 25 Aug 2026 ]

Specialist
Dr. Smith

Type
[ Consultation ]

Notes
[________________________]

Documents
[ Upload ]

[ Save ]
```

После сохранения:

```text
Encounter created
```

А attached documents идут через общий processing pipeline.

---

# 34. Admin UI

Не надо делать его первым.

После MVP:

```text
admin/
├── users
├── specialists
├── organizations
├── access-grants
├── processing-jobs
└── audit-log
```

Особенно полезен:

```text
Processing jobs
```

где admin видит:

```text
Document
Status
Worker
Attempts
Started
Finished
Error
```

---

# 35. Design system

Создать:

```text
components/ui/
```

и определить:

```text
Button
Input
Textarea
Select
Checkbox
Radio
Dialog
Drawer
Tabs
Badge
Card
Table
Dropdown
Toast
Skeleton
Alert
Progress
Avatar
Pagination
```

А медицинские компоненты строить поверх них.

---

# 36. Цветовая система

Я бы не делал интерфейс визуально похожим на hospital software из 2005 года.

Стиль:

```text
clean
calm
minimal
high contrast
large touch targets
```

Особенно mobile.

Кнопки:

```text
minimum ~44px touch target
```

---

# 37. Accessibility

Сразу:

```text
WCAG-oriented
keyboard navigation
screen readers
focus states
ARIA
semantic HTML
contrast
```

Особенно важно для медицинского продукта.

Не делать:

```text
<div onClick=...>
```

вместо:

```text
<button>
```

---

# 38. Responsive architecture

Breakpoints не должны диктовать domain logic.

Компонент:

```text
MedicalRecord
```

один.

Layout:

```text
mobile
tablet
desktop
```

разный.

Например:

```text
useMediaQuery
```

использовать только там, где действительно требуется поведенческое отличие.

В основном предпочитать CSS responsive layout.

---

# 39. API client

Создать package:

```text
packages/api-client/
```

Pipeline:

```text
FastAPI
   ↓
OpenAPI
   ↓
generated TypeScript client
   ↓
TanStack Query wrappers
```

Например:

```text
packages/api-client/
├── generated/
├── hooks/
└── index.ts
```

---

# 40. Query architecture

Например:

```typescript
useMedicalRecord(patientId)
```

внутри:

```text
TanStack Query
   ↓
API client
   ↓
FastAPI
```

Query keys:

```text
["current-user"]

["patient", patientId]

["medical-record", patientId]

["documents", patientId]

["document", documentId]

["analytics", patientId, metric]

["encounters", patientId]
```

---

# 41. Cache invalidation

Например:

```text
Upload document
      ↓
confirm upload
      ↓
invalidate:
["documents", patientId]
["medical-record", patientId]
```

После завершения AI:

```text
invalidate:
["document", documentId]
["medical-record", patientId]
["timeline", patientId]
["analytics", patientId]
```

---

# 42. Error handling

Создать единый формат:

```text
ApiError
```

Frontend должен уметь:

```text
401 → login
403 → access denied
404 → not found
409 → conflict
422 → validation error
429 → retry later
500 → generic error
503 → service unavailable
```

---

# 43. UI error states

Каждая страница должна иметь:

```text
loading
empty
error
success
```

Например documents:

```text
Loading...
```

```text
No documents yet

[Upload document]
```

```text
Could not load documents

[Try again]
```

---

# 44. Skeletons

Не показывать на каждом месте spinner.

Например:

```text
MedicalRecordSkeleton
DocumentCardSkeleton
PatientTableSkeleton
AnalyticsSkeleton
```

Это будет намного приятнее на мобильном интернете.

---

# 45. Notifications

Для первой версии:

```text
toast
```

Например:

```text
Document uploaded successfully
```

Но медицинские события лучше показывать также persistent status:

```text
Analysis failed
[Open document]
```

---

# 46. Offline strategy

На первом этапе:

**не делать полноценный offline mode.**

Но:

```text
PWA
cached static assets
retry uploads
```

можно добавить.

Medical record не следует бездумно кэшировать offline из-за чувствительности данных.

---

# 47. Security frontend

Минимальный checklist:

```text
HTTPS
HttpOnly cookies
Secure cookies
SameSite
CSRF protection
CSP
XSS protection
No tokens in localStorage
No sensitive data in URL
No medical data in analytics tools
No medical data in console.log
```

Особенно последнее.

Не:

```javascript
console.log(patient)
```

в production.

---

# 48. Analytics

Обычная product analytics:

```text
page viewed
button clicked
upload started
upload completed
```

Но нельзя отправлять:

```text
patient name
diagnosis
lab values
document content
```

в third-party analytics.

Я бы вообще отложил analytics SDK до security/compliance review.

---

# 49. SEO

SEO имеет смысл только для публичных страниц:

```text
/
about
help
privacy
terms
```

Не нужно SSR/SEO ради:

```text
/patient
/specialist
/medical-record
```

Это private application.

---

# 50. Performance

Основные targets:

```text
Fast initial load
small JS bundles
lazy load PDF viewer
lazy load charts
virtualized long lists
image optimization
pagination
```

Особенно:

```text
DocumentViewer
Charts
Patient list
```

не должны загружать всё сразу.

---

# 51. Testing strategy

Три уровня.

### Unit

```text
Vitest
```

Тестируем:

```text
validation
formatters
permissions UI logic
upload state machine
utility functions
```

### Component

```text
React Testing Library
```

Тестируем:

```text
LoginForm
UploadForm
DocumentCard
MedicalTimeline
Analytics
```

### E2E

```text
Playwright
```

---

# 52. Основной E2E сценарий клиента

```text
Register
 ↓
Login
 ↓
Dashboard
 ↓
Upload PDF
 ↓
Upload succeeds
 ↓
Document queued
 ↓
Document processing
 ↓
Document completed
 ↓
Open document
 ↓
View extracted medical data
 ↓
Medical record updated
 ↓
Analytics updated
```

---

# 53. Основной E2E сценарий specialist

```text
Login
 ↓
Specialist dashboard
 ↓
Patients
 ↓
Open patient
 ↓
Medical record
 ↓
Documents
 ↓
Open document
 ↓
Create encounter
 ↓
Upload new document
 ↓
Document processed
 ↓
Record updated
```

---

# 54. Authorization E2E

Обязательно:

```text
Patient A
   ↓
cannot access
   ↓
Patient B
```

и:

```text
Specialist A
   ↓
no grant
   ↓
403
```

после:

```text
Patient B
   ↓
grant access
   ↓
Specialist A
   ↓
allowed
```

и:

```text
Grant expires
   ↓
403
```

---

# 55. Development phases

Теперь конкретно порядок разработки.

## Phase 0 — Project bootstrap

```text
Next.js
TypeScript
pnpm
ESLint
Prettier
Tailwind
shadcn
Vitest
Playwright
```

Результат:

```text
npm/pnpm run dev
```

открывает приложение.

---

# 56. Phase 1 — Design system

Создать:

```text
Button
Input
Card
Dialog
Drawer
Tabs
Badge
Alert
Skeleton
```

и layout:

```text
MobileHeader
DesktopSidebar
BottomNavigation
PageHeader
```

Результат:

готовый application shell.

---

# 57. Phase 2 — API client

Подключить:

```text
FastAPI OpenAPI
```

Сгенерировать:

```text
TypeScript API types
```

Реализовать:

```text
auth
me
patients
documents
```

---

# 58. Phase 3 — Authentication

Сделать:

```text
/login
/register
/verify
/forgot-password
```

Потом:

```text
protected routes
role routing
session handling
logout
```

---

# 59. Phase 4 — Client dashboard

```text
/app/dashboard
```

С:

```text
patient summary
recent documents
recent medical events
quick upload
```

---

# 60. Phase 5 — Document upload

Это первый важный vertical slice.

```text
File picker
 ↓
validation
 ↓
init
 ↓
S3 upload
 ↓
confirm
 ↓
processing status
```

Должен работать полностью с реальным backend.

---

# 61. Phase 6 — Medical Record

Создать:

```text
Overview
Timeline
Documents
Results
```

Сначала read-only.

---

# 62. Phase 7 — Analytics

Добавить:

```text
Metric cards
Charts
Date filters
Metric filters
```

Например:

```text
Blood pressure
Glucose
Hemoglobin
Weight
```

Только если backend предоставляет эти данные.

---

# 63. Phase 8 — Specialist

Создать:

```text
/specialist/dashboard
/specialist/patients
/specialist/patients/[id]
```

---

# 64. Phase 9 — Access management

UI:

```text
Grant access
Revoke access
Access expiration
Permission selection
```

и соответствующие states.

---

# 65. Phase 10 — Encounters

Specialist:

```text
Create encounter
Edit encounter
View encounter
Attach documents
```

---

# 66. Phase 11 — Admin

Только после основного workflow:

```text
users
specialists
organizations
jobs
audit
```

---

# 67. Phase 12 — PWA

После стабильного web MVP:

```text
manifest
icons
install prompt
service worker
offline shell
```

Но без offline medical data.

---

# 68. Phase 13 — Production hardening

Проверить:

```text
Security
Performance
Accessibility
Error handling
Monitoring
Logging
CSP
Cookies
Rate limiting
Upload security
```

---

# 69. Phase 14 — Prepare for mobile

Не создавать mobile app сразу.

Сначала вынести:

```text
packages/
├── api-client
├── contracts
├── validation
└── shared-utils
```

И убедиться, что domain logic не зависит от:

```text
window
document
Next.js router
browser APIs
```

где это возможно.

---

# 70. После этого Expo

Тогда:

```text
apps/
├── web/
│   └── Next.js
│
└── mobile/
    └── Expo
```

Shared:

```text
packages/
├── api-client
├── validation
├── contracts
└── shared-utils
```

UI не обязательно shared.

---

# 71. Что получится в результате

### Web

```text
Next.js
   │
   ├── Client portal
   ├── Specialist portal
   └── Admin portal
```

### Backend

```text
FastAPI
```

### Processing

```text
RabbitMQ
   │
   ├── Marker
   └── AI
```

### Storage

```text
PostgreSQL
S3
Qdrant
```

### Future

```text
Expo
 ├── iOS
 └── Android
```

---

# 72. Приоритеты MVP

Я бы **не пытался сделать весь перечисленный UI сразу**.

### MVP-1

```text
Auth
+
Client dashboard
+
Upload document
+
Document status
+
Medical record
+
Extracted result
```

### MVP-2

```text
Analytics
+
Timeline
+
Specialist
```

### MVP-3

```text
Access management
+
Encounters
+
Admin
```

### MVP-4

```text
PWA
+
Mobile preparation
```

### MVP-5

```text
Expo iOS/Android
```

---

# 73. Рекомендуемая структура конечного `apps/web`

В итоге я бы целился примерно сюда:

```text
apps/web/
│
├── public/
│
├── src/
│   │
│   ├── app/
│   │   ├── (public)/
│   │   │   ├── page.tsx
│   │   │   ├── login/
│   │   │   └── register/
│   │   │
│   │   ├── (authenticated)/
│   │   │   ├── layout.tsx
│   │   │   ├── dashboard/
│   │   │   ├── medical-record/
│   │   │   ├── documents/
│   │   │   ├── analytics/
│   │   │   └── profile/
│   │   │
│   │   ├── specialist/
│   │   │   ├── layout.tsx
│   │   │   ├── dashboard/
│   │   │   ├── patients/
│   │   │   └── patients/[patientId]/
│   │   │
│   │   └── admin/
│   │
│   ├── features/
│   │   ├── auth/
│   │   ├── patients/
│   │   ├── medical-record/
│   │   ├── documents/
│   │   ├── encounters/
│   │   ├── analytics/
│   │   ├── specialist-access/
│   │   └── admin/
│   │
│   ├── components/
│   │   ├── ui/
│   │   ├── layout/
│   │   └── feedback/
│   │
│   ├── lib/
│   │   ├── api/
│   │   ├── auth/
│   │   ├── query/
│   │   ├── storage/
│   │   └── utils/
│   │
│   ├── hooks/
│   ├── types/
│   └── styles/
│
├── tests/
│   ├── unit/
│   ├── components/
│   └── e2e/
│
├── next.config.ts
├── package.json
├── tsconfig.json
└── ...
```

---

# 74. Итого — последовательность разработки

Если свести весь план к одной цепочке:

```text
1. Next.js project
        ↓
2. Design system
        ↓
3. API client / OpenAPI
        ↓
4. Authentication
        ↓
5. Application shell
        ↓
6. Client dashboard
        ↓
7. S3 document upload
        ↓
8. Processing status
        ↓
9. Medical Record
        ↓
10. Extracted medical data
        ↓
11. Timeline
        ↓
12. Analytics
        ↓
13. Specialist portal
        ↓
14. Patient access
        ↓
15. Encounters
        ↓
16. Admin
        ↓
17. E2E/security/accessibility
        ↓
18. PWA
        ↓
19. Extract shared packages
        ↓
20. Expo mobile app
```

**Главное:** я бы не начинал с красивого dashboard. Первый frontend milestone должен быть **полный сквозной workflow**:

```text
Register
  ↓
Login
  ↓
Client dashboard
  ↓
Upload PDF/image
  ↓
S3
  ↓
RabbitMQ
  ↓
Marker
  ↓
AI
  ↓
Medical data
  ↓
Medical Record
  ↓
Frontend отображает результат
```

После этого frontend уже имеет настоящий фундамент, а не набор mock screens.

И с учётом вашей существующей backend-документации я бы следующим шагом зафиксировал **конкретный Frontend Architecture Specification**: структуру `apps/web`, routing map, все страницы/экраны, component hierarchy, API endpoints, TypeScript types, query keys и responsive behavior для каждого экрана. Это станет уже практически техническим ТЗ, по которому можно начинать реализацию.
