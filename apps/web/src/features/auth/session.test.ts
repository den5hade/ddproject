import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearSession,
  getAccessToken,
  getRefreshToken,
  hasSession,
  refreshTokens,
  storeTokens,
} from "./session";

const ACCESS_1 = "access-1";
const REFRESH_1 = "refresh-1";
const ACCESS_2 = "access-2";
const REFRESH_2 = "refresh-2";

function tokenResponse(access: string, refresh: string): Response {
  return new Response(
    JSON.stringify({ access_token: access, refresh_token: refresh }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

beforeEach(() => {
  localStorage.clear();
  clearSession();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("session store", () => {
  it("stores and clears tokens", () => {
    expect(hasSession()).toBe(false);
    storeTokens(ACCESS_1, REFRESH_1);
    expect(getAccessToken()).toBe(ACCESS_1);
    expect(getRefreshToken()).toBe(REFRESH_1);
    expect(hasSession()).toBe(true);
    clearSession();
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
    expect(hasSession()).toBe(false);
  });

  it("hasSession is true when only the refresh token exists (page reload)", () => {
    localStorage.setItem("ddp.refresh", REFRESH_1);
    expect(hasSession()).toBe(true);
  });
});

describe("refreshTokens", () => {
  it("performs silent refresh and stores rotated tokens", async () => {
    localStorage.setItem("ddp.refresh", REFRESH_1);
    const fetchMock = vi.fn().mockResolvedValue(tokenResponse(ACCESS_2, REFRESH_2));
    vi.stubGlobal("fetch", fetchMock);

    const ok = await refreshTokens();

    expect(ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ refresh_token: REFRESH_1 });
    expect(getAccessToken()).toBe(ACCESS_2);
    expect(getRefreshToken()).toBe(REFRESH_2);
  });

  it("clears session when refresh token is rejected (rotation revoked)", async () => {
    localStorage.setItem("ddp.refresh", REFRESH_1);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 400 })),
    );

    const ok = await refreshTokens();

    expect(ok).toBe(false);
    expect(hasSession()).toBe(false);
  });

  it("resolves false without touching fetch when no refresh token stored", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const ok = await refreshTokens();

    expect(ok).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("is single-flight: concurrent callers share one request", async () => {
    localStorage.setItem("ddp.refresh", REFRESH_1);
    let resolveFetch!: (value: Response) => void;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const first = refreshTokens();
    const second = refreshTokens();
    resolveFetch(tokenResponse(ACCESS_2, REFRESH_2));
    const [a, b] = await Promise.all([first, second]);

    expect(a).toBe(true);
    expect(b).toBe(true);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("keeps session on network failure (caller shows offline error)", async () => {
    storeTokens(ACCESS_1, REFRESH_1);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));

    const ok = await refreshTokens();

    expect(ok).toBe(false);
    expect(getAccessToken()).toBe(ACCESS_1);
    expect(getRefreshToken()).toBe(REFRESH_1);
  });
});
