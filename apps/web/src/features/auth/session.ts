/*
 * Token session store (plan §5.1, decision D2).
 * - access_token: memory only (module-scoped), lost on reload by design —
 *   restored silently via refresh on first authenticated call.
 * - refresh_token: localStorage["ddp.refresh"].
 * - refreshTokens() is single-flight: concurrent 401s share one request.
 *
 * Uses raw fetch for /auth/refresh to avoid a circular dependency
 * with lib/api/client.ts.
 */

const REFRESH_KEY = "ddp.refresh";
const REFRESH_PATH = "/api/v1/auth/refresh";

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

export function hasSession(): boolean {
  return accessToken !== null || getRefreshToken() !== null;
}

export function storeTokens(accessTokenValue: string, refreshTokenValue: string): void {
  accessToken = accessTokenValue;
  try {
    localStorage.setItem(REFRESH_KEY, refreshTokenValue);
  } catch {
    /* private mode etc. — session simply won't survive reload */
  }
}

export function clearSession(): void {
  accessToken = null;
  try {
    localStorage.removeItem(REFRESH_KEY);
  } catch {
    /* ignore */
  }
}

let inflight: Promise<boolean> | null = null;

/** Single-flight silent refresh. Resolves true when a fresh access token is set. */
export function refreshTokens(): Promise<boolean> {
  inflight ??= doRefresh().finally(() => {
    inflight = null;
  });
  return inflight;
}

async function doRefresh(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;
  try {
    const res = await fetch(REFRESH_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) {
      clearSession();
      return false;
    }
    const data = (await res.json()) as {
      access_token?: string;
      refresh_token?: string;
    };
    if (!data.access_token || !data.refresh_token) {
      clearSession();
      return false;
    }
    storeTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    // Network failure: keep tokens, let the caller surface an offline error
    // instead of logging the user out.
    return false;
  }
}
