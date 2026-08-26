import type { ReactNode } from "react";
import { DocumentCard } from "./DocumentCard";
import type { DocumentResponse } from "../api";
import { groupDocumentsByMonth } from "../grouping";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { strings } from "@/lib/i18n/strings";

/*
 * Presentational month-grouped document list (SG §56).
 * Shared by /documents and /medical-record tabs.
 * Caller supplies the empty state (differs per screen).
 */

export function DocumentList({
  documents,
  isPending,
  isError,
  onRetry,
  emptyState,
}: {
  documents?: DocumentResponse[];
  isPending?: boolean;
  isError?: boolean;
  onRetry?: () => void;
  emptyState?: ReactNode;
}) {
  if (isPending) {
    return (
      <div className="space-y-3" aria-hidden="true">
        <Skeleton className="h-5 w-36" />
        <Skeleton className="h-[72px] w-full rounded-xl" />
        <Skeleton className="h-[72px] w-full rounded-xl" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-xl border border-border bg-surface px-5 py-4">
        <p className="text-[15px] text-ink-secondary">{strings.common.errorTitle}</p>
        {onRetry && (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            {strings.common.retry}
          </Button>
        )}
      </div>
    );
  }

  const groups = groupDocumentsByMonth(documents ?? []);
  if (groups.length === 0) {
    return emptyState ?? null;
  }

  return (
    <div className="flex flex-col gap-8">
      {groups.map((group) => (
        <section
          key={group.key}
          aria-label={group.label}
          className="flex flex-col gap-3"
        >
          <h2 className="text-sm font-semibold text-ink-secondary">{group.label}</h2>
          <div className="flex flex-col gap-3">
            {group.documents.map((document) => (
              <DocumentCard key={document.id} document={document} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
