import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { IdentityForm } from "@/features/auth/components/IdentityForm";
import { useRequestOtp } from "@/features/auth/hooks";
import { hasSession } from "@/features/auth/session";
import { ApiError } from "@/lib/api/errors";
import { strings } from "@/lib/i18n/strings";
import { cn } from "@/lib/utils";

/*
 * Rotating headline on the login screen (SG §44–47 motion).
 * Words are decorative (`aria-hidden`); a single sr-only <h1> keeps the
 * page's heading structure and gives screen readers a stable "Вход" label,
 * so an auto-rotating live region never spams them.
 * Auto-cycle halts under prefers-reduced-motion (static first word).
 */
const ROTATING_WORDS = [
  "исследования",
  "заключения",
  "снимки",
  "анализы",
  "выписки",
  "показатели",
];

const ROTATE_INTERVAL_MS = 3600;

function WordCarousel() {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (media.matches) return;
    const timer = setInterval(
      () => setIndex((i) => (i + 1) % ROTATING_WORDS.length),
      ROTATE_INTERVAL_MS,
    );
    return () => clearInterval(timer);
  }, []);

  return (
    <div
      aria-hidden="true"
      className="relative flex h-[43px] items-center justify-center text-[36px] font-semibold leading-tight text-ink-faint"
    >
      {ROTATING_WORDS.map((word, i) => (
        <span
          key={word}
          className={cn(
            "absolute inset-0 flex items-center justify-center transition-opacity duration-[400ms] ease-out",
            i === index ? "opacity-100" : "opacity-0",
          )}
        >
          {word}
        </span>
      ))}
    </div>
  );
}

/*
 * SG §25–26: calm column layout, no card walls.
 * Guard: authenticated users never see login (plan §5.1).
 */
export function LoginPage() {
  if (hasSession()) return <Navigate to="/" replace />;
  return <LoginScreen />;
}

function LoginScreen() {
  const navigate = useNavigate();
  const requestOtp = useRequestOtp();
  const [serverError, setServerError] = useState<string | null>(null);

  const handleSubmit = (identity: string) => {
    setServerError(null);
    requestOtp.mutate(identity, {
      onSuccess: () => {
        navigate("/login/verify", { state: { identity } });
      },
      onError: (err) => {
        setServerError(
          err instanceof ApiError && err.status === 429
            ? strings.verify.rateLimited
            : (err instanceof ApiError ? err.message : strings.common.errorTitle),
        );
      },
    });
  };

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-[400px] flex-col justify-center px-5 py-8">
      <div className="mb-10">
        <h1 className="sr-only">{strings.login.title}</h1>
        <WordCarousel />
      </div>

      <IdentityForm
        pending={requestOtp.isPending}
        serverError={serverError}
        onSubmit={handleSubmit}
      />

      <p className="mt-10 text-center text-sm text-ink-muted">
        {strings.common.privacyLine}
      </p>
    </main>
  );
}
