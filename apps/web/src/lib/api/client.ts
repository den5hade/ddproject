import createClient, { type Middleware } from "openapi-fetch";
import { ApiError, parseApiError } from "./errors";
import type { paths } from "./schema";
import {
  getAccessToken,
  hasSession,
  refreshTokens,
} from "@/features/auth/session";

/*
 * Typed API client (plan §5.4).
 * Generated schema paths include the full "/api/v1" prefix, so baseUrl is "".
 * The Vite dev proxy (and nginx in prod) forwards /api to the backend.
 */

const authMiddleware: Middleware = {
  onRequest({ request }) {
    const token = getAccessToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(authMiddleware);

interface ClientResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

async function safeBody(response: Response): Promise<unknown> {
  try {
    return await response.clone().json();
  } catch {
    return undefined;
  }
}

/** Converts an openapi-fetch result into data or throws ApiError. */
export async function unwrap<T>(
  result: ClientResult<T> | Promise<ClientResult<T>>,
): Promise<T> {
  const { data, error, response } = await result;
  if (response.ok && data !== undefined) return data;
  throw parseApiError(response.status, error ?? (await safeBody(response)));
}

/**
 * Executes a typed call; on 401 performs a single-flight silent refresh
 * and replays the call exactly once (plan §5.1).
 */
export async function authed<T>(
  call: () => ClientResult<T> | Promise<ClientResult<T>>,
): Promise<T> {
  try {
    return await unwrap(call());
  } catch (err) {
    if (
      err instanceof ApiError &&
      err.status === 401 &&
      hasSession() &&
      (await refreshTokens())
    ) {
      return unwrap(call());
    }
    throw err;
  }
}
