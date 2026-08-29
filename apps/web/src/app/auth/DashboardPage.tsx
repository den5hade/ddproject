import { Link } from "react-router-dom";
import { ChevronRight, FileText } from "lucide-react";
import { useMe, useMyPatient } from "@/features/auth/hooks";
import {
  DocumentCard,
} from "@/features/documents/components/DocumentCard";
import { useMyPatientDocuments } from "@/features/documents/hooks";
import { greetingForHour } from "@/lib/utils/format";
import { strings } from "@/lib/i18n/strings";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/*
 * Client dashboard (plan §6.4).
 * Record > metrics (SG §2): one record summary card + recent documents.
 * No metric tiles / counters (SG §2 anti-pattern).
 */

const RECENT_LIMIT = 5;

export function DashboardPage() {
  const me = useMe();
  const patient = useMyPatient();
  const documents = useMyPatientDocuments(patient.data?.id);

  const firstName = patient.data?.person.name.trim();
  const greetingKey =
    firstName && firstName.length > 0 ? greetingForHour(new Date().getHours()) : null;
  const GREETINGS = {
    morning: strings.dashboard.greetingMorning,
    afternoon: strings.dashboard.greetingAfternoon,
    evening: strings.dashboard.greetingEvening,
  } as const;
  const greeting =
    greetingKey && firstName
      ? `${GREETINGS[greetingKey]}, ${firstName}`
      : strings.dashboard.greetingFallback;

  const recent = documents.data?.slice(0, RECENT_LIMIT) ?? [];
  const isEmpty = !documents.isPending && recent.length === 0;

  return (
    <div className="flex flex-col gap-10">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[28px] font-semibold leading-tight text-ink lg:text-[30px]">
            {documents.isPending || patient.isPending ? (
              <Skeleton className="h-8 w-56" />
            ) : (
              greeting
            )}
          </h1>
          {!me.isPending && me.data?.email && (
            <p className="mt-1 text-sm text-ink-muted">{me.data.email}</p>
          )}
        </div>

        <Link to="/documents" className={cn(buttonVariants())}>
          {strings.dashboard.uploadCta}
        </Link>
      </header>

      {/* Medical record summary — the primary object (SG §2) */}
      {patient.isPending ? (
        <Skeleton className="h-28 w-full rounded-xl" />
      ) : (
        <Link to="/medical-record" className="block rounded-xl">
          <Card className="transition-colors duration-150 ease-out hover:bg-surface-muted">
            <CardContent className="flex items-center justify-between p-5">
              <span>
                <span className="block text-lg font-semibold text-ink">
                  {strings.dashboard.recordCardTitle}
                </span>
                <span className="mt-1 block text-sm text-ink-secondary">
                  {strings.dashboard.recordCardSubtitle}
                </span>
                <span className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-primary">
                  {strings.dashboard.recordCardCta}
                  <ChevronRight size={16} strokeWidth={2} />
                </span>
              </span>
              <HeartGlyph />
            </CardContent>
          </Card>
        </Link>
      )}

      {/* Recent documents */}
      <section aria-labelledby="recent-documents-title">
        <div className="mb-4 flex items-baseline justify-between">
          <h2
            id="recent-documents-title"
            className="text-xl font-semibold text-ink"
          >
            {strings.dashboard.recentTitle}
          </h2>
          {!isEmpty && (
            <Link
              to="/documents"
              className="text-sm font-medium text-primary underline-offset-4 hover:underline"
            >
              {strings.dashboard.openAll}
            </Link>
          )}
        </div>

        {documents.isPending ? (
          <div className="space-y-3" aria-hidden="true">
            <Skeleton className="h-[72px] w-full rounded-xl" />
            <Skeleton className="h-[72px] w-full rounded-xl" />
            <Skeleton className="h-[72px] w-full rounded-xl" />
          </div>
        ) : documents.isError ? (
          <ErrorRow onRetry={() => void documents.refetch()} />
        ) : isEmpty ? (
          <EmptyDocuments />
        ) : (
          <div className="flex flex-col gap-3">
            {recent.map((document) => (
              <DocumentCard key={document.id} document={document} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ErrorRow({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-border bg-surface px-5 py-4">
      <p className="text-[15px] text-ink-secondary">
        {strings.common.errorTitle}
      </p>
      <Button variant="secondary" size="sm" onClick={onRetry}>
        {strings.common.retry}
      </Button>
    </div>
  );
}

function EmptyDocuments() {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border-strong bg-surface px-6 py-10 text-center">
      <FileText size={24} strokeWidth={2} className="text-ink-muted" aria-hidden="true" />
      <p className="font-medium text-ink">{strings.dashboard.emptyDocumentsTitle}</p>
      <p className="max-w-[360px] text-sm leading-relaxed text-ink-secondary">
        {strings.dashboard.emptyDocumentsText}
      </p>
    </div>
  );
}

/** Small calm line icon instead of illustration (SG §30). */
function HeartGlyph() {
  return (
    <svg
      aria-hidden="true"
      width="40"
      height="40"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.25"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0 text-primary opacity-60"
    >
      <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" />
      <path d="M3.22 12H9.5l.5-1 2 4.5 2-7 1.5 3.5h5.27" />
    </svg>
  );
}
