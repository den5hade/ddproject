import { NavLink, NavLinkProps, Navigate, Outlet } from "react-router-dom";
import { Files, HeartPulse, Home, User } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useMe, useMyPatient } from "@/features/auth/hooks";
import { hasSession } from "@/features/auth/session";
import { strings } from "@/lib/i18n/strings";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

/*
 * AppShell (plan §6.3).
 * Mobile: fixed bottom navigation, max 4 items (SG §27).
 * Desktop ≥lg: quiet left sidebar, active = soft bg + dark green (SG §28–29).
 * Content column capped at ~720px for reading comfort (SG §58).
 */

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: strings.nav.home, icon: Home },
  { to: "/medical-record", label: strings.nav.record, icon: HeartPulse },
  { to: "/documents", label: strings.nav.documents, icon: Files },
  { to: "/profile", label: strings.nav.profile, icon: User },
];

function NavLinks({ layout }: { layout: "sidebar" | "bottom" }) {
  return (
    <>
      {NAV_ITEMS.map(({ to, label, icon: Icon }) => {
        const linkProps: NavLinkProps = {
          to,
          end: to === "/",
          children: undefined,
        };
        return (
          <NavLink
            key={to}
            {...linkProps}
            className={({ isActive }) =>
              cn(
                "transition-colors duration-150 ease-out",
                layout === "sidebar"
                  ? "flex items-center gap-3 rounded-lg px-3 py-2 text-[15px]"
                  : "flex flex-col items-center gap-1 px-1 py-2 text-caption",
                isActive
                  ? layout === "sidebar"
                    ? "bg-primary-soft font-medium text-primary-dark"
                    : "text-primary-dark"
                  : layout === "sidebar"
                    ? "text-ink-secondary hover:bg-surface-muted hover:text-ink"
                    : "text-ink-secondary",
              )
            }
          >
            <Icon size={layout === "sidebar" ? 20 : 20} strokeWidth={2} />
            {label}
          </NavLink>
        );
      })}
    </>
  );
}

function Brand() {
  return (
    <span className="font-semibold tracking-tight text-ink">
      {strings.brand.appName}
    </span>
  );
}

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

  return (
    <div className="min-h-dvh">
      {/* Desktop sidebar (SG §28–29) */}
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-60 flex-col border-r border-border bg-surface px-4 py-6 lg:flex">
        <div className="mb-10 px-3 text-lg">
          <Brand />
        </div>
        <nav aria-label="Основная навигация" className="flex flex-col gap-1">
          <NavLinks layout="sidebar" />
        </nav>
      </aside>

      <div className="lg:pl-60">
        {/* Mobile top bar: brand only (SG §27 — no hamburger for MVP) */}
        <header className="sticky top-0 z-10 flex items-center justify-center border-b border-border bg-surface/95 py-3 backdrop-blur lg:hidden">
          <Brand />
        </header>

        <main className="mx-auto w-full max-w-[720px] px-5 pt-6 pb-24 lg:py-10">
          <Outlet context={{ me: me.data, patient: patient.data }} />
        </main>
      </div>

      {/* Mobile bottom navigation (SG §27) */}
      <nav
        aria-label="Основная навигация"
        className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-4 border-t border-border bg-surface lg:hidden"
      >
        <NavLinks layout="bottom" />
      </nav>
    </div>
  );
}
