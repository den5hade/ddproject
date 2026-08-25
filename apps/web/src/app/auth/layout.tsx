import { Navigate, Outlet } from "react-router-dom";
import { useMe, useMyPatient } from "@/features/auth/hooks";
import { hasSession } from "@/features/auth/session";
import { strings } from "@/lib/i18n/strings";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

/*
 * Guarded shell (plan §5.1, §6.3).
 * M2: bootstrap gate only — full AppShell nav lands in M3.
 * Bootstrap: parallel GET /auth/me + GET /patients/me; a stale access
 * token is silently restored by the 401→refresh→replay flow in authed().
 */
export function AuthLayout() {
  const me = useMe();
  const patient = useMyPatient();

  if (!hasSession()) return <Navigate to="/login" replace />;

  if (me.isPending || patient.isPending) {
    return (
      <main className="mx-auto w-full max-w-[720px] px-5 py-8">
        <Skeleton className="h-8 w-48" />
        <div className="mt-6 space-y-4">
          <Skeleton className="h-24 w-full rounded-xl" />
          <Skeleton className="h-16 w-full rounded-xl" />
        </div>
      </main>
    );
  }

  if (me.isError || patient.isError) {
    // Session was already wiped by a failed refresh → bounce to login.
    if (!hasSession()) return <Navigate to="/login" replace />;
    return (
      <main className="mx-auto flex min-h-dvh max-w-[720px] flex-col items-center justify-center gap-4 px-5">
        <p className="text-[15px] text-ink-secondary">
          {strings.common.errorTitle}
        </p>
        <Button
          variant="secondary"
          onClick={() => {
            void me.refetch();
            void patient.refetch();
          }}
        >
          {strings.common.retry}
        </Button>
      </main>
    );
  }

  return <Outlet context={{ me: me.data, patient: patient.data }} />;
}
