import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { IdentityForm } from "@/features/auth/components/IdentityForm";
import { useRequestOtp } from "@/features/auth/hooks";
import { hasSession } from "@/features/auth/session";
import { ApiError } from "@/lib/api/errors";
import { strings } from "@/lib/i18n/strings";

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
        <h1 className="text-[30px] font-semibold leading-tight text-ink">
          {strings.login.title}
        </h1>
        <p className="mt-2 text-[15px] leading-relaxed text-ink-secondary">
          {strings.login.subtitle}
        </p>
      </div>

      <IdentityForm
        pending={requestOtp.isPending}
        serverError={serverError}
        onSubmit={handleSubmit}
      />

      <p className="mt-10 text-sm text-ink-muted">{strings.common.privacyLine}</p>
    </main>
  );
}
