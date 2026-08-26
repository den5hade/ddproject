import { api, authed, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type TokenResponse = components["schemas"]["TokenResponse"];
export type UserResponse = components["schemas"]["UserResponse"];

/** POST /auth/request-otp — public, returns 202. */
export function requestOtp(identity: string) {
  return unwrap(
    api.POST("/api/v1/auth/request-otp", { body: { identity } }),
  );
}

/** POST /auth/verify — public. Caller stores tokens via session.storeTokens. */
export function verifyOtp(body: components["schemas"]["VerifyOtpRequest"]) {
  return unwrap<TokenResponse>(api.POST("/api/v1/auth/verify", { body }));
}

/** POST /auth/logout — 204; fire-and-forget, session cleared by caller. */
export async function logout(refreshToken: string): Promise<void> {
  await api.POST("/api/v1/auth/logout", { body: { refresh_token: refreshToken } });
}

/** GET /auth/me */
export function getMe() {
  // authed(): on cold reload the access token lives only in memory —
  // the first call goes out unauthenticated (401) and MUST trigger the
  // silent refresh + replay like every other protected endpoint.
  return authed(() => api.GET("/api/v1/auth/me"));
}
