import { execSync } from "node:child_process";

/*
 * E2E auth helper (plan §7/M7).
 * The backend delivers OTP codes to Redis (notification-worker is
 * SMTP in prod; in dev the code lives at `otp:code:{identity}`).
 * We read it straight from the dev Redis container.
 */

const API = "http://localhost:8000";
const REDIS_CONTAINER = "development-redis-1";

export function uniqueIdentity(): string {
  return `e2e-${Date.now()}-${Math.floor(Math.random() * 10_000)}@example.com`;
}

export function requestOtp(identity: string): void {
  const res = execSync(
    `curl -s -X POST ${API}/api/v1/auth/request-otp -H "Content-Type: application/json" -d '${JSON.stringify({ identity })}'`,
    { encoding: "utf8" },
  );
  if (!res.includes("OTP sent")) {
    throw new Error(`request-otp failed: ${res}`);
  }
}

/** Reads the code from dev Redis, tolerating brief propagation delays. */
export function readOtpCode(identity: string): string {
  const deadline = Date.now() + 10_000;
  let last = "";
  while (Date.now() < deadline) {
    last = execSync(
      `docker exec ${REDIS_CONTAINER} redis-cli --raw GET "otp:code:${identity}"`,
      { encoding: "utf8" },
    ).trim();
    if (/^\d{6}$/.test(last)) return last;
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 500);
  }
  throw new Error(`no OTP code in redis for ${identity}: "${last}"`);
}
