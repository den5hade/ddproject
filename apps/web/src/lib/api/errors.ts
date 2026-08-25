/*
 * Unified API error model (plan §5.4).
 * FastAPI error shapes handled:
 *   - {"detail": "string"}                       → message
 *   - {"detail": [{loc, msg, type}, ...]}        → 422 field errors
 *   - anything else                              → generic by status
 */

export type FieldErrors = Record<string, string>;

export class ApiError extends Error {
  readonly status: number;
  readonly fields?: FieldErrors;

  constructor(status: number, message: string, fields?: FieldErrors) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.fields = fields;
  }
}

type FastAPIValidationItem = { loc?: unknown; msg?: unknown };

function isValidationItems(value: unknown): value is FastAPIValidationItem[] {
  return (
    Array.isArray(value) &&
    value.every((item) => typeof item === "object" && item !== null)
  );
}

/** Maps loc like ["body","identity"] → field key "identity". */
function fieldFromLoc(loc: unknown): string | null {
  if (!Array.isArray(loc)) return null;
  const parts = loc.filter(
    (part): part is Exclude<typeof part, symbol> => typeof part !== "symbol",
  );
  const bodyIdx = parts.indexOf("body");
  const fieldParts =
    bodyIdx >= 0 ? parts.slice(bodyIdx + 1) : parts.length ? parts.slice(-1) : [];
  return fieldParts.length ? String(fieldParts.join(".")) : null;
}

export function parseApiError(status: number, body: unknown): ApiError {
  if (
    body !== null &&
    typeof body === "object" &&
    "detail" in (body as Record<string, unknown>)
  ) {
    const detail = (body as Record<string, unknown>).detail;
    if (typeof detail === "string") return new ApiError(status, detail);
    if (isValidationItems(detail)) {
      const fields: FieldErrors = {};
      let firstMessage = "Проверьте правильность заполнения";
      for (const item of detail) {
        const msg = typeof item.msg === "string" ? item.msg : "";
        const field = fieldFromLoc(item.loc);
        if (field) fields[field] ??= humanizeValidationMessage(msg);
        if (!firstMessage && msg) firstMessage = msg;
      }
      return new ApiError(status, firstMessage, fields);
    }
  }
  return new ApiError(status, defaultMessageForStatus(status));
}

function humanizeValidationMessage(msg: string): string {
  // FastAPI messages look like "Value error, identity is not a valid email"
  return msg.replace(/^Value error,\s*/i, "").replace(/^String should match/i, "Неверный формат");
}

export function defaultMessageForStatus(status: number): string {
  switch (status) {
    case 400:
      return "Некорректный запрос";
    case 401:
      return "Сессия истекла, войдите заново";
    case 403:
      return "Нет доступа";
    case 404:
      return "Не найдено";
    case 409:
      return "Конфликт данных";
    case 413:
      return "Файл слишком большой";
    case 415:
      return "Неподдерживаемый тип файла";
    case 422:
      return "Проверьте правильность заполнения";
    case 429:
      return "Слишком много запросов, попробуйте позже";
    case 503:
      return "Сервис временно недоступен";
    default:
      return status >= 500
        ? "Ошибка сервера, попробуйте снова"
        : "Что-то пошло не так";
  }
}

/** True for statuses where retrying cannot help (client-side problem). */
export function isClientError(status: number): boolean {
  return status >= 400 && status < 500;
}
