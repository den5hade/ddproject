/*
 * UI strings — single source (plan D7, SG §51–52).
 * Plain typed dict; swap for i18n framework later without touching components.
 * Terminology per SG §52–53. Banned: "AI", "AI Insights", "Smart Analytics".
 */
export const strings = {
  brand: {
    appName: "Здоровье",
    tagline: "Ваши медицинские документы — в одном месте",
  },
  common: {
    loading: "Загрузка…",
    retry: "Попробовать снова",
    cancel: "Отмена",
    save: "Сохранить",
    errorTitle: "Не удалось загрузить данные",
    privacyLine: "Ваши документы приватны.",
  },
  login: {
    title: "Вход",
    subtitle: "Введите email или телефон, мы пришлём код подтверждения",
    identityLabel: "Email или телефон",
    identityPlaceholder: "you@example.com",
    submit: "Получить код",
    submitting: "Отправляем…",
  },
  verify: {
    title: "Код подтверждения",
    subtitlePrefix: "Мы отправили код на",
    inputLabel: "Шестизначный код",
    cellAriaLabel: (n: number) => `Цифра ${n} из 6`,
    resend: "Отправить снова",
    resendIn: (s: number) => `Отправить снова через ${s} с`,
    changeIdentity: "Изменить адрес",
    wrongCode: "Неверный или устаревший код. Запросите новый.",
    rateLimited: "Код уже отправлен. Подождите минуту перед повторной отправкой.",
    verifying: "Проверяем…",
    confirm: "Подтвердить",
  },
  nav: {
    home: "Главная",
    record: "Карта",
    documents: "Документы",
    profile: "Профиль",
  },
  documents: {
    title: "Документы",
    subtitle: "Все ваши медицинские документы",
    add: "Добавить",
    takePhoto: "Сделать фото",
    chooseFile: "Выбрать файл",
    dropzoneText: "Перетащите PDF или изображение сюда",
    dropzoneOr: "или",
    chooseFileShort: "Выбрать файл",
    uploading: "Загрузка",
    uploadingPercent: (pct: number) => `${pct}%`,
    cancelUpload: "Отменить",
    retryUpload: "Повторить",
    uploadErrorTitle: "Не удалось загрузить файл",
    uploadedToast: "Документ загружен",
    emptyTitle: "Пока нет документов",
    emptyText:
      "Загрузите первый медицинский документ, чтобы начать вести личную историю здоровья.",
    filtersAll: "Все",
    filtersLaboratory: "Лаборатория",
    filtersVisits: "Приёмы",
    filtersOther: "Другое",
  },
  dashboard: {
    greetingMorning: "Доброе утро",
    greetingAfternoon: "Добрый день",
    greetingEvening: "Добрый вечер",
    greetingFallback: "Здравствуйте",
    recordCardTitle: "Медицинская карта",
    recordCardSubtitle: "Ваши документы и результаты",
    recordCardCta: "Открыть карту",
    recentTitle: "Последние документы",
    uploadCta: "Загрузить документ",
    emptyDocumentsTitle: "Пока нет документов",
    emptyDocumentsText:
      "Загрузите первый медицинский документ, чтобы начать вести личную историю здоровья.",
    openAll: "Все документы",
  },
} as const;

export type Strings = typeof strings;
