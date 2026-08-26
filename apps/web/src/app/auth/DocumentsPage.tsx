import { useMemo, useState } from "react";
import { FolderOpen } from "lucide-react";
import { Uploader } from "@/features/documents/components/Uploader";
import {
  DocumentList,
} from "@/features/documents/components/DocumentList";
import {
  filterDocuments,
  type DocumentFilter,
} from "@/features/documents/grouping";
import { useMyPatientDocuments } from "@/features/documents/hooks";
import { useMyPatient } from "@/features/auth/hooks";
import { strings } from "@/lib/i18n/strings";
import { cn } from "@/lib/utils";

/*
 * Documents page (plan §6.5).
 * Header + «Добавить» (SG §42) · month-grouped DocumentList (SG §56) ·
 * client-side type chips · four UI states.
 * The single <Uploader> instance owns the mobile sheet, desktop
 * dropzone, and the upload progress/error row.
 */

const FILTERS: Array<{ key: DocumentFilter; label: string }> = [
  { key: "all", label: strings.documents.filtersAll },
  { key: "laboratory", label: strings.documents.filtersLaboratory },
  { key: "visits", label: strings.documents.filtersVisits },
  { key: "other", label: strings.documents.filtersOther },
];

export function DocumentsPage() {
  const patient = useMyPatient();
  const documents = useMyPatientDocuments(patient.data?.id);
  const [filter, setFilter] = useState<DocumentFilter>("all");

  const visible = useMemo(
    () => filterDocuments(documents.data ?? [], filter),
    [documents.data, filter],
  );
  const isEmpty =
    !documents.isPending && !documents.isError && documents.data?.length === 0;

  return (
    <div className="flex flex-col gap-8">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[28px] font-semibold leading-tight text-ink lg:text-[30px]">
            {strings.documents.title}
          </h1>
          <p className="mt-1 text-[15px] text-ink-secondary">
            {strings.documents.subtitle}
          </p>
        </div>
        {patient.data && <Uploader patientId={patient.data.id} />}
      </header>

      {/* Type filter chips */}
      {!isEmpty && (
        <div role="group" aria-label="Фильтр по типу" className="flex flex-wrap gap-2">
          {FILTERS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
              className={cn(
                "rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors duration-150 ease-out",
                filter === key
                  ? "border-transparent bg-primary-soft text-primary-dark"
                  : "border-border bg-surface text-ink-secondary hover:bg-surface-muted hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      <DocumentList
        documents={visible}
        isPending={documents.isPending}
        isError={documents.isError}
        onRetry={() => void documents.refetch()}
        emptyState={<EmptyDocuments />}
      />
    </div>
  );
}

function EmptyDocuments() {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border-strong bg-surface px-6 py-12 text-center">
      <FolderOpen size={24} strokeWidth={2} className="text-ink-muted" aria-hidden="true" />
      <p className="font-medium text-ink">{strings.documents.emptyTitle}</p>
      <p className="max-w-[380px] text-sm leading-relaxed text-ink-secondary">
        {strings.documents.emptyText}
      </p>
      <p className="mt-1 flex items-center gap-1.5 text-xs text-ink-muted">
        PDF, JPEG, PNG, TIFF ≤ 50 МБ
      </p>
    </div>
  );
}
