import { Link } from "react-router-dom";
import { useLogout, useMe, useMyPatientSummary } from "@/features/auth/hooks";
import { LogoutButton } from "@/features/auth/components/LogoutButton";
import { strings } from "@/lib/i18n/strings";
import { buttonVariants, Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/*
 * Profile (plan §6.8): calm overview — summary stats, read-only account,
 * a «Изменить данные» entry to the /profile/edit form, and logout as a
 * round icon in the header [SG §2/§49]. The form lives on ProfileEditPage;
 * this page never mutates.
 */

export function ProfilePage() {
  const me = useMe();
  const summary = useMyPatientSummary();
  const logout = useLogout();

  const accountRows: Array<[string, string]> = [
    [strings.profile.email, me.data?.email ?? ""],
    [strings.profile.phone, me.data?.phone ?? ""],
  ].filter(([, value]) => value.length > 0) as Array<[string, string]>;

  return (
    <div className="flex flex-col gap-10">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[28px] font-semibold leading-tight text-ink lg:text-[30px]">
            {strings.profile.title}
          </h1>
          <p className="mt-1 text-[15px] text-ink-secondary">
            {strings.profile.subtitle}
          </p>
        </div>
        <LogoutButton onLogout={() => logout.mutate()} />
      </header>

      {/* Summary stats — exactly two counters, calm card (SG §2) */}
      <section aria-labelledby="summary-section" className="flex flex-col gap-4">
        <h2 id="summary-section" className="text-xl font-semibold text-ink">
          {strings.profile.sectionSummary}
        </h2>

        {summary.isPending ? (
          <div className="space-y-3" aria-hidden="true">
            <Skeleton className="h-14 w-full rounded-xl" />
            <Skeleton className="h-14 w-full rounded-xl" />
          </div>
        ) : summary.isError ? (
          <ErrorCard onRetry={() => void summary.refetch()} />
        ) : (
          <dl className="rounded-xl border border-border bg-surface px-5 py-2">
            <StatRow label={strings.profile.statDocuments} value={summary.data?.documents_count ?? 0} />
            <StatRow
              label={strings.profile.statReadAccess}
              value={summary.data?.read_grants_count ?? 0}
            />
          </dl>
        )}
      </section>

      {/* Account — read-only, no payment/subscription info */}
      <section aria-labelledby="account-section" className="flex flex-col gap-4">
        <h2 id="account-section" className="text-xl font-semibold text-ink">
          {strings.profile.sectionAccount}
        </h2>

        {me.isPending ? (
          <div className="space-y-3" aria-hidden="true">
            <Skeleton className="h-14 w-full rounded-xl" />
          </div>
        ) : accountRows.length > 0 ? (
          <dl className="rounded-xl border border-border bg-surface px-5 py-2">
            {accountRows.map(([label, value]) => (
              <StatRow key={label} label={label} value={value} />
            ))}
          </dl>
        ) : null}
      </section>

      {/* Personal data — form lives on /profile/edit */}
      <Link to="/profile/edit" className={cn(buttonVariants({ variant: "secondary" }))}>
        {strings.profile.ctaEditData}
      </Link>
    </div>
  );
}

function StatRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-border py-3.5 last:border-b-0">
      <dt className="text-sm text-ink-secondary">{label}</dt>
      <dd className="text-right text-[15px] font-medium text-ink">{value}</dd>
    </div>
  );
}

function ErrorCard({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-border bg-surface px-5 py-4">
      <p className="text-[15px] text-ink-secondary">{strings.common.errorTitle}</p>
      <Button variant="secondary" size="sm" onClick={onRetry}>
        {strings.common.retry}
      </Button>
    </div>
  );
}