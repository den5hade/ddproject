import { useCanonical, useExtractions } from "../hooks";
import { normalizeCanonical, type ExtractionView } from "../canonical";
import { parseExtractionData, type Observation } from "../extraction";
import { PrescriptionView } from "./PrescriptionView";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { strings } from "@/lib/i18n/strings";

/*
 * Extracted information viewer (SG §35–38): canonical extraction data
 * rendered per document type (laboratory / prescription / generic), falling
 * back to the legacy extractions shape for older documents. Wording is
 * strictly descriptive — no interpretation (SG §36–37), no "AI" anywhere.
 */

export function ExtractionViewer({ documentId }: { documentId: string }) {
  const canonical = useCanonical(documentId);
  const extractions = useExtractions(documentId);

  if (canonical.isPending) {
    return (
      <div className="space-y-3" aria-hidden="true">
        <Skeleton className="h-[84px] w-full rounded-xl" />
        <Skeleton className="h-[84px] w-full rounded-xl" />
      </div>
    );
  }

  if (canonical.data) {
    const view = normalizeCanonical(canonical.data.data);
    if (view) return <ViewRenderer view={view} />;
  }

  // Canonical not available (404 / empty) → legacy extractions feed.
  if (extractions.isPending) {
    return (
      <div className="space-y-3" aria-hidden="true">
        <Skeleton className="h-[84px] w-full rounded-xl" />
        <Skeleton className="h-[84px] w-full rounded-xl" />
      </div>
    );
  }

  if (extractions.isError || canonical.isError) {
    return (
      <div className="rounded-xl border border-border bg-surface px-5 py-4">
        <p className="text-[15px] text-ink-secondary">
          {strings.common.errorTitle}
        </p>
      </div>
    );
  }

  const all = extractions.data ?? [];
  const latest = all.length > 0 ? all[all.length - 1] : undefined;
  const observations: Observation[] | null =
    latest === undefined ? null : parseExtractionData(latest.data);

  if (observations === null) {
    return <EmptyState />;
  }

  return (
    <div className="flex flex-col gap-3" role="list" aria-label={strings.detail.tabExtraction}>
      {observations.map((observation, index) => (
        <ObservationCard
          key={`${observation.name}-${index}`}
          observation={observation}
        />
      ))}
    </div>
  );
}

function ViewRenderer({ view }: { view: ExtractionView }) {
  switch (view.kind) {
    case "laboratory":
      return (
        <div className="flex flex-col gap-3" role="list" aria-label={strings.detail.tabExtraction}>
          {view.observations.map((observation, index) => (
            <ObservationCard
              key={`${observation.name}-${index}`}
              observation={observation}
            />
          ))}
        </div>
      );
    case "prescription":
      return (
        <PrescriptionView
          medications={view.medications}
          doctor={view.doctor}
          issuedAt={view.issuedAt}
        />
      );
    case "generic":
    case "legacy":
      return (
        <div className="flex flex-col gap-3" role="list" aria-label={strings.detail.tabExtraction}>
          {view.observations.map((observation, index) => (
            <ObservationCard
              key={`${observation.name}-${index}`}
              observation={observation}
            />
          ))}
        </div>
      );
  }
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border-strong bg-surface px-6 py-10 text-center">
      {/* SG §33: «Извлечённая информация», no AI branding */}
      <p className="text-[15px] font-medium text-ink">
        {strings.detail.extractionEmptyTitle}
      </p>
      <p className="max-w-[380px] text-sm leading-relaxed text-ink-secondary">
        {strings.detail.extractionEmptyText}
      </p>
    </div>
  );
}

function ObservationCard({ observation }: { observation: Observation }) {
  const status = rangeStatus(observation);
  return (
    <div role="listitem" className="rounded-xl border border-border bg-surface px-5 py-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[15px] font-medium text-ink">{observation.name}</p>
        {status && (
          <Badge tone="warning">{status}</Badge>
        )}
      </div>

      {/* Value + unit on one calm line */}
      <p className="mt-1 text-lg text-ink-secondary">
        {observation.value}
        {observation.unit && (
          <span className="ml-1.5 text-sm">{observation.unit}</span>
        )}
      </p>

      {/* SG §35: reference or explicit unavailability; SG §36: neutral wording */}
      {observation.reference ? (
        <p className="mt-2 text-sm text-ink-muted">
          {strings.detail.referenceRange}: {observation.reference}
        </p>
      ) : null}
    </div>
  );
}

/** Range status is computed from numbers only — no interpretation (SG §36). */
function rangeStatus(
  observation: Observation,
): "Выше диапазона" | "Ниже диапазона" | null {
  if (observation.referenceMin === undefined || observation.referenceMax === undefined) {
    return null;
  }
  const value = Number(String(observation.value).replace(",", "."));
  if (!Number.isFinite(value)) return null;
  if (value > observation.referenceMax) return strings.detail.aboveRange;
  if (value < observation.referenceMin) return strings.detail.belowRange;
  return null;
}