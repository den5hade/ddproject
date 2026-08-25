# Health Document App — Style Guide v1.0

## 1. Product personality

Приложение должно ощущаться как:

> **Спокойное, надежное, приватное и простое место для хранения собственной медицинской истории.**

### Ключевые характеристики

| Характеристика | Как выражаем                                                |
| -------------- | ----------------------------------------------------------- |
| Calm           | приглушённые цвета, много whitespace                        |
| Trustworthy    | предсказуемый UI, четкая типографика                        |
| Minimal        | мало декоративных элементов                                 |
| Private        | визуально не перегружать профиль/данные                     |
| Personal       | обращение к пользователю, персональная история              |
| Medical        | структурированные данные, но без ощущения hospital software |
| Modern         | современная типографика и аккуратные компоненты             |

### Не хотим

```text
❌ ярко-синий medical dashboard
❌ градиенты
❌ glassmorphism
❌ большие hero illustrations
❌ постоянно движущиеся элементы
❌ десятки карточек
❌ чрезмерные badges
❌ dashboard с 20 метриками
❌ «AI everywhere»
```

---

# 2. Основная визуальная идея

Я бы построил интерфейс вокруг трех визуальных уровней:

```text
BACKGROUND
     ↓
CONTENT
     ↓
IMPORTANT INFORMATION
```

Например:

```text
┌──────────────────────────────────────┐
│                                      │
│  Medical record                      │
│                                      │
│  Your health documents and results   │
│                                      │
│  ─────────────────────────────────   │
│                                      │
│  Recent                              │
│                                      │
│  Blood test                          │
│  15 Aug 2026                         │
│                                      │
│  Cardiologist report                 │
│  10 Aug 2026                         │
│                                      │
└──────────────────────────────────────┘
```

Не:

```text
┌──────┐ ┌──────┐ ┌──────┐
│ 128  │ │  12  │ │  94% │
│ docs │ │ labs │ │ ...  │
└──────┘ └──────┘ └──────┘
```

В нашем случае **documents и medical record важнее dashboard metrics**.

---

# 3. Color system

Я бы выбрал очень нейтральную базу с **мягким desaturated green/teal accent**.

Не медицинский `#0066FF`.

Например:

```text
Primary
#557A72

Primary dark
#3F625B

Primary light
#E8F0EE
```

Это создаёт ассоциацию:

```text
health
calm
nature
trust
```

но не выглядит как стандартный hospital UI.

---

# 4. Neutral palette

Основной background:

```text
Background
#F8F9F7
```

Surface:

```text
Surface
#FFFFFF
```

Secondary surface:

```text
Surface muted
#F1F3F0
```

Borders:

```text
Border
#E2E6E2
```

Strong border:

```text
Border strong
#D1D7D2
```

---

# 5. Text colors

Primary:

```text
#202522
```

Secondary:

```text
#626B65
```

Muted:

```text
#8A928C
```

Disabled:

```text
#B5BBB7
```

Таким образом:

```text
Primary text
████████████

Secondary
████████

Muted
████
```

Без pure black.

Я бы избегал:

```text
#000000
```

для обычного текста.

---

# 6. Semantic colors

Нам всё равно нужны состояния.

### Success

```text
Color
#4F7A63

Background
#EAF2EC
```

### Warning

```text
Color
#9A7842

Background
#F7F1E5
```

### Error

```text
Color
#9A5A56

Background
#F7EAEA
```

### Information

```text
Color
#58718A

Background
#EAF0F4
```

Важно: **цвет не должен быть единственным способом показать состояние**.

Например:

```text
✓ Completed
```

а не просто зелёная точка.

---

# 7. Color usage ratio

Я бы придерживался примерно:

```text
70% neutral background / surfaces
20% text / borders
8% primary accent
2% semantic colors
```

Accent не должен заполнять половину экрана.

---

# 8. Dark mode

Для первой версии я бы **не делал dark mode**.

Причина не в сложности реализации, а в приоритетах.

Сейчас важнее:

```text
light theme
accessibility
mobile UX
document readability
medical data readability
```

Архитектуру при этом сделать так, чтобы dark theme можно было добавить позже через design tokens.

---

# 9. Typography

Я бы использовал **Inter** или системный sans-serif.

Например:

```text
font-family:
Inter,
ui-sans-serif,
system-ui,
sans-serif;
```

Для медицинских документов и длинного текста можно позже использовать отдельный reading font, но для MVP это не требуется.

---

# 10. Typography scale

Не нужно слишком много размеров.

```text
Display
36px / 44px

H1
30px / 38px

H2
24px / 32px

H3
20px / 28px

Body large
17px / 26px

Body
15px / 23px

Small
13px / 20px

Caption
12px / 18px
```

На mobile:

```text
H1
28px

H2
22px

H3
18px
```

---

# 11. Font weights

Только:

```text
400 Regular
500 Medium
600 Semibold
```

В большинстве случаев:

```text
body → 400
labels → 500
headings → 600
```

Не использовать 700/800 повсеместно.

Это хорошо соответствует спокойной эстетике.

---

# 12. Headings

Заголовки должны быть короткими.

Хорошо:

```text
Medical record
```

```text
Recent documents
```

```text
Blood test
```

Плохо:

```text
Your complete personal medical document history
```

---

# 13. Spacing system

Используем базу `4px`.

```text
4
8
12
16
20
24
32
40
48
64
80
```

Основные интервалы:

```text
label → input
8px

input → input
16px

section content
24px

section → section
40px

page sections
48–64px
```

---

# 14. Border radius

Не делать всё чрезмерно круглым.

Я бы использовал:

```text
small
6px

default
10px

large
14px

modal
16px
```

Buttons:

```text
8px
```

Cards:

```text
12px
```

---

# 15. Shadows

Очень осторожно.

Основной UI:

```text
box-shadow: none;
```

Карточки разделяются:

```text
background
+
border
```

а не тенью.

Shadow только для floating elements:

```text
modal
popover
dropdown
mobile bottom sheet
```

Например:

```text
0 8px 30px rgba(...)
```

Но в design token shadow должен быть один-два уровня, а не 10 вариантов.

---

# 16. Borders

Основной способ визуального разделения:

```text
1px solid #E2E6E2
```

Особенно:

```text
cards
inputs
tables
document list
navigation
```

---

# 17. Cards

Карточки нужны, но умеренно.

### Document card

```text
┌────────────────────────────────────┐
│ PDF                         •••     │
│                                    │
│ Blood test                         │
│ 15 August 2026                     │
│                                    │
│ Completed                          │
└────────────────────────────────────┘
```

Не:

```text
┌────────────────────────┐
│ 🧪 Blood test          │
│                        │
│ 15 Aug                 │
│                        │
│ ┌────────────────────┐ │
│ │ 135 g/L            │ │
│ │ NORMAL             │ │
│ └────────────────────┘ │
│                        │
│ [VIEW] [DOWNLOAD]      │
└────────────────────────┘
```

Второй вариант слишком dashboard-like.

---

# 18. Documents — главный визуальный объект

Поскольку основной продукт — **хранение документов**, документ должен быть первым классом UI entity.

Например:

```text
Document
├── title
├── type
├── date
├── source
├── status
└── extracted data
```

Визуально:

```text
[PDF] Blood test
      15 Aug 2026

      Completed
```

---

# 19. File type icons

Очень ограниченный набор:

```text
PDF
Image
Document
Lab result
Medical visit
```

Не нужно 30 разных иконок.

Можно использовать Lucide.

---

# 20. Icons

Основной icon library:

**Lucide Icons**

Стиль:

```text
stroke
2px
rounded
```

Размеры:

```text
16px
20px
24px
```

Не использовать icons как декоративный шум.

---

# 21. Primary button

```text
┌────────────────────┐
│  Upload document   │
└────────────────────┘
```

Primary:

```text
background: primary
color: white
height: 44px
radius: 8px
```

На mobile:

```text
min-height: 48px
```

---

# 22. Secondary button

```text
┌────────────────────┐
│  View record       │
└────────────────────┘
```

Белый/neutral background + border.

---

# 23. Tertiary actions

Например:

```text
View
Download
Open
```

могут быть обычными text buttons.

Не нужно превращать каждое действие в отдельную кнопку.

---

# 24. Destructive actions

Удаление документа:

```text
Delete document
```

не должно быть primary red button.

Лучше:

```text
•••
   Delete
```

и confirmation:

```text
Delete document?

This document will be removed from your medical record.

[Cancel] [Delete]
```

---

# 25. Inputs

Простой стиль:

```text
Email

┌──────────────────────────────────┐
│ you@example.com                  │
└──────────────────────────────────┘
```

Height:

```text
44–48px
```

Border:

```text
#D9DEDA
```

Focus:

```text
primary border
+
subtle focus ring
```

---

# 26. Forms

Не помещать всё в giant card.

Хорошо:

```text
Create account

Email
[....................]

Password
[....................]

[Create account]
```

Плохо:

```text
┌─────────────────────────────┐
│                             │
│       CREATE ACCOUNT        │
│                             │
│ Email                       │
│ [...]                       │
│ Password                    │
│ [...]                       │
│ ...                         │
└─────────────────────────────┘
```

---

# 27. Navigation — mobile

Для клиента я бы использовал bottom navigation:

```text
┌────────────────────────────────────┐
│                                    │
│             content                │
│                                    │
├────────────────────────────────────┤
│ Home │ Record │ Documents │ Profile│
└────────────────────────────────────┘
```

Четыре пункта максимум.

---

# 28. Navigation — desktop

Desktop:

```text
┌──────────────┬─────────────────────────────┐
│              │                             │
│ Health       │                             │
│              │        Content              │
│ Home         │                             │
│ Record       │                             │
│ Documents    │                             │
│ Analytics    │                             │
│              │                             │
│              │                             │
│ Profile      │                             │
└──────────────┴─────────────────────────────┘
```

Sidebar спокойный, без яркого active background.

---

# 29. Active navigation

Например:

```text
Medical record
```

может иметь:

```text
background: #E8F0EE
color: #3F625B
```

Не использовать насыщенный зелёный прямоугольник.

---

# 30. Empty states

Очень важны.

Например новый пользователь:

```text
Your medical record is empty

Upload your first medical document to start building
your personal health history.

[Upload document]
```

Без огромной иллюстрации.

Можно использовать маленькую line icon.

---

# 31. Processing states

Так как backend асинхронный, status UI будет очень важен.

Предлагаю четыре основных состояния:

```text
Uploaded
Processing
Ready
Failed
```

В UI:

```text
Uploaded
Processing
Ready
Needs attention
```

Последнее лучше для пользователя, чем техническое `Failed`.

---

# 32. Processing animation

Минимум анимации.

Например:

```text
Processing
● ● ●
```

с очень медленной opacity animation.

Не делать:

```text
spinning document
flying particles
AI magic
gradient animation
```

---

# 33. AI branding

Я бы **не выделял AI визуально слишком сильно**.

Пользователю важно:

```text
"Information extracted"
```

а не:

```text
"AI MAGIC ✨"
```

Например:

```text
Extracted information

Hemoglobin
135 g/L
```

---

# 34. Medical analytics

На первом этапе аналитика должна быть **описательной**, а не диагностической.

Например:

```text
Hemoglobin

135 g/L

Your previous result:
132 g/L

Trend
Stable
```

Не:

```text
You may have iron deficiency.
```

если такая медицинская интерпретация не является частью валидированного продукта.

---

# 35. Reference ranges

Если backend получил reference range:

```text
Hemoglobin

135 g/L

Reference
120–160 g/L
```

Если reference range неизвестен:

```text
135 g/L

Reference range unavailable
```

Не пытаться самостоятельно придумывать диапазон.

---

# 36. Medical status colors

Не делать:

```text
green = healthy
red = sick
```

Слишком сильное утверждение.

Лучше:

```text
Within provided reference range
Above provided reference range
Below provided reference range
Reference unavailable
```

И только если данные действительно позволяют это определить.

---

# 37. Data visualization

Минимальная аналитика:

```text
metric
value
unit
date
previous value
trend
```

Например:

```text
Weight

72.4 kg

↓ 1.2 kg
since last measurement
```

График показывается только когда есть достаточное количество данных.

---

# 38. Tables

Для mobile таблицы не использовать.

Вместо:

```text
| Date | Test | Result | Range |
```

использовать:

```text
15 Aug 2026

Hemoglobin
135 g/L

Reference 120–160 g/L
```

Desktop может использовать table view.

---

# 39. Timeline style

Timeline должен быть очень спокойным.

```text
August 2026

│
● 15 Aug
│  Blood test
│  Laboratory
│
● 10 Aug
│  Cardiologist visit
│  Dr. Smith
│
● 02 Aug
│  Prescription
```

Тонкая линия, маленькие точки.

---

# 40. Document preview

На mobile:

```text
┌──────────────────────────────┐
│                              │
│         PDF preview          │
│                              │
│                              │
└──────────────────────────────┘

Blood test
15 Aug 2026

[Open document]
```

Не нужно показывать огромный PDF viewer сразу на dashboard.

---

# 41. Modal vs page

Правило:

### Modal

Для:

```text
confirm delete
quick action
short forms
```

### Full page

Для:

```text
document
medical record
encounter
analytics
patient
```

Medical information должна иметь пространство.

---

# 42. Mobile upload UX

Это один из ключевых flows.

```text
Documents

                    [+ Add]

Recent

Blood test
PDF · 15 Aug

Doctor visit
PDF · 10 Aug
```

Нажатие:

```text
+ Add
```

открывает bottom sheet:

```text
Add document

[ Take photo ]

[ Choose from device ]

[ Cancel ]
```

Это естественнее для мобильного приложения.

---

# 43. Desktop upload UX

На desktop:

```text
[ + Upload document ]
```

и drag & drop.

То есть UX адаптируется:

```text
Mobile
→ actionsheet

Desktop
→ button + drag/drop
```

---

# 44. Motion design

Основной принцип:

> **Animation should explain state, not decorate the interface.**

Разрешаем:

```text
150–200ms
```

для:

```text
hover
focus
button state
drawer
modal
accordion
```

---

# 45. Что анимируем

Да:

```text
button hover
dropdown
drawer
modal
toast
upload progress
processing status
```

Не:

```text
page transitions
floating cards
animated backgrounds
animated icons everywhere
scroll animations
```

---

# 46. Motion easing

Основная:

```text
ease-out
```

Например:

```text
150ms ease-out
```

Для drawer:

```text
200–250ms
```

---

# 47. Reduced motion

Обязательно поддержать:

```text
prefers-reduced-motion
```

При этом:

```text
animations → disabled/reduced
```

---

# 48. Loading philosophy

Используем:

```text
Skeleton
```

для content.

```text
Progress
```

для upload.

```text
Spinner
```

только для маленьких локальных действий.

Например:

```text
[ Uploading... ◌ ]
```

---

# 49. Toasts

Минимальные:

```text
Document uploaded
Document deleted
Access granted
Changes saved
```

Не делать toast для каждого network request.

---

# 50. Privacy visual language

Это особенно важно для приложения.

Не нужно постоянно показывать:

```text
🔒 SECURE
```

Это быстро превращается в marketing noise.

Лучше спокойный текст:

```text
Your documents are private.
```

в appropriate places.

---

# 51. Language

Если основной рынок русскоязычный, интерфейс должен поддерживать:

```text
ru
```

но архитектуру сразу сделать:

```text
i18n
```

с возможностью:

```text
en
de
```

позже.

Не зашивать UI strings непосредственно в компоненты.

---

# 52. Terminology

Нужно заранее стандартизировать терминологию.

Например:

```text
Document
Документ

Medical record
Медицинская карта

Specialist
Специалист

Encounter
Приём

Laboratory result
Результат лабораторного исследования

Extracted information
Извлечённая информация
```

Я бы избегал слова:

```text
AI analysis
```

в пользовательском интерфейсе, если оно не необходимо.

---

# 53. Dashboard terminology

Не:

```text
AI Insights
Health Intelligence
Smart Analytics
```

А:

```text
Recent results
Health history
Measurements
Documents
```

Это гораздо спокойнее и вызывает меньше необоснованных ожиданий.

---

# 54. Brand direction

Я бы ориентировался примерно на визуальную смесь:

```text
modern personal finance app
+
minimal health app
+
document management
```

но без копирования конкретных продуктов.

Главный визуальный принцип:

> **Content first, interface second.**

---

# 55. Design tokens

В React/Next.js проекте все значения нужно вынести в tokens.

Например:

```text
styles/
├── globals.css
├── tokens.css
└── themes.css
```

И концептуально:

```css
--color-background
--color-surface
--color-primary
--color-primary-soft

--color-text
--color-text-secondary
--color-text-muted

--color-border

--color-success
--color-warning
--color-error
--color-info

--radius-sm
--radius-md
--radius-lg

--space-1
--space-2
--space-3
...
```

Компоненты не должны содержать произвольные цвета.

---

# 56. Пример общей страницы

Например `/documents`:

```text
┌─────────────────────────────────────────────┐
│                                             │
│  Documents                         + Upload │
│                                             │
│  All your medical documents                │
│                                             │
│  [All] [Laboratory] [Visits] [Other]       │
│                                             │
│  ─────────────────────────────────────────  │
│                                             │
│  August 2026                                │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │ PDF                                   │  │
│  │ Blood test                            │  │
│  │ 15 Aug 2026                           │  │
│  │                                       │  │
│  │ Completed                         ›   │  │
│  └───────────────────────────────────────┘  │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │ PDF                                   │  │
│  │ Cardiologist report                   │  │
│  │ 10 Aug 2026                           │  │
│  │                                       │  │
│  │ Completed                         ›   │  │
│  └───────────────────────────────────────┘  │
│                                             │
└─────────────────────────────────────────────┘
```

Это примерно тот уровень плотности, который я бы держал во всём приложении.

---

# 57. Самое важное правило для этого продукта

Я бы сформулировал его так:

> **Don't make the interface look more intelligent than the product actually is.**

На данном этапе продукт делает:

```text
Store documents
      ↓
Extract information
      ↓
Organize medical history
      ↓
Show basic trends
```

Поэтому UI тоже должен быть:

```text
Store
Organize
Understand
```

а не:

```text
Diagnose
Predict
Recommend
```

---

# 58. Финальная визуальная система

Таким образом, предлагаю зафиксировать:

```text
PRODUCT STYLE
────────────────────────────

Minimal
Calm
Private
Personal
Editorial
Medical but not clinical


COLORS
────────────────────────────

Background      #F8F9F7
Surface         #FFFFFF
Surface muted   #F1F3F0

Primary         #557A72
Primary dark    #3F625B
Primary soft    #E8F0EE

Text            #202522
Text secondary  #626B65
Text muted      #8A928C

Border          #E2E6E2


TYPOGRAPHY
────────────────────────────

Inter / system sans

400 Regular
500 Medium
600 Semibold


SPACING
────────────────────────────

4px base


RADIUS
────────────────────────────

6 / 8 / 10 / 12 / 16px


SHADOW
────────────────────────────

Almost none


MOTION
────────────────────────────

150–250ms
ease-out
state-driven only


ICONS
────────────────────────────

Lucide
16 / 20 / 24px


LAYOUT
────────────────────────────

Mobile first
Content centered
Generous whitespace
Cards used sparingly


UX
────────────────────────────

Documents first
Medical record second
Analytics third
AI invisible/minimal
```

Я бы следующим этапом превратил этот style guide в **конкретный UI Design System для реализации**: `design tokens → Tailwind config → shadcn/ui customization → typography → buttons → inputs → cards → document cards → status badges → navigation → mobile bottom navigation`, а затем на его основе спроектировал **5 ключевых экранов клиента**: Login, Dashboard, Documents, Document Details и Medical Record. Это даст уже практически готовую визуальную спецификацию для разработки.
