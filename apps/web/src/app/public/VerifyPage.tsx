import { useEffect, useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { OtpInput } from "@/features/auth/components/OtpInput";
import { useRequestOtp, useVerifyOtp } from "@/features/auth/hooks";
import { hasSession } from "@/features/auth/session";
import { ApiError } from "@/lib/api/errors";
import { strings } from "@/lib/i18n/strings";
import { Button } from "@/components/ui/button";

const RESEND_COOLDOWN_SECONDS = 60;

interface VerifyLocationState {
  identity?: string;
}

/** Identity survives reload during OTP entry (sessionStorage fallback). */
function useIdentity(): string | null {
  const location = useLocation();
  const state = location.state as VerifyLocationState | null;
  useEffect(() => {
    if (state?.identity) {
      try {
        sessionStorage.setItem("ddp.identity", state.identity);
      } catch {
        /* ignore */
      }
    }
  }, [state?.identity]);
  if (state?.identity) return state.identity;
  try {
    return sessionStorage.getItem("ddp.identity");
  } catch {
    return null;
  }
}

export function VerifyPage() {
  if (hasSession()) return <Navigate to="/" replace />;
  return <VerifyScreen />;
}

function VerifyScreen() {
  const identity = useIdentity();
  if (!identity) return <Navigate to="/login" replace />;
  return <VerifyForm identity={identity} />;
}

function VerifyForm({ identity }: { identity: string }) {
  const verify = useVerifyOtp();
  const requestOtp = useRequestOtp();

  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN_SECONDS);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(
      () => setCooldown((s) => (s > 0 ? s - 1 : 0)),
      1000,
    );
    return () => clearInterval(timer);
  }, [cooldown]);

  const submit = (nextCode: string) => {
    setError(null);
    verify.mutate(
      { identity, code: nextCode },
      {
        onError: (err) => {
          setError(
            err instanceof ApiError && err.status === 400
              ? strings.verify.wrongCode
              : err instanceof ApiError
                ? err.message
                : strings.common.errorTitle,
          );
        },
      },
    );
  };

  const resend = () => {
    setError(null);
    requestOtp.mutate(identity, {
      onSuccess: () => setCooldown(RESEND_COOLDOWN_SECONDS),
      onError: (err) =>
        setError(
          err instanceof ApiError && err.status === 429
            ? strings.verify.rateLimited
            : err.message,
        ),
    });
  };

  const masked = identity.includes("@")
    ? identity
    : `${identity.slice(0, 4)}…${identity.slice(-2)}`;

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-[400px] flex-col justify-center px-5 py-8">
      <div className="mb-10">
        <h1 className="text-[30px] font-semibold leading-tight text-ink">
          {strings.verify.title}
        </h1>
        <p className="mt-2 text-[15px] leading-relaxed text-ink-secondary">
          {strings.verify.subtitlePrefix}{" "}
          <span className="font-medium text-ink">{masked}</span>
        </p>
        <Link
          to="/login"
          className="mt-1 inline-block text-sm text-primary underline-offset-4 hover:underline"
        >
          {strings.verify.changeIdentity}
        </Link>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (code.length === 6) submit(code);
        }}
        noValidate
        className="flex flex-col gap-4"
      >
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-ink">
            {strings.verify.inputLabel}
          </span>
          <OtpInput
            value={code}
            onChange={setCode}
            onComplete={submit}
            disabled={verify.isPending}
          />
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
        </div>

        <Button
          type="submit"
          disabled={verify.isPending || code.length !== 6}
          className="w-full"
        >
          {verify.isPending ? strings.verify.verifying : strings.verify.confirm}
        </Button>

        <Button
          type="button"
          variant="ghost"
          disabled={cooldown > 0 || requestOtp.isPending}
          onClick={resend}
          className="w-full"
        >
          {cooldown > 0 ? strings.verify.resendIn(cooldown) : strings.verify.resend}
        </Button>
      </form>

      <p className="mt-10 text-sm text-ink-muted">{strings.common.privacyLine}</p>
    </main>
  );
}
