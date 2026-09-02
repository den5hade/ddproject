import type { Medication } from "../canonical";
import { strings } from "@/lib/i18n/strings";

/*
 * Prescription view (canonical `prescription` payload): medication cards
 * with dosage / frequency / duration, plus issuing doctor and date in a
 * quiet secondary block. No interpretation — descriptive only (SG §36).
 */

export function PrescriptionView({
  medications,
  doctor,
  issuedAt,
}: {
  medications: Medication[];
  doctor?: string;
  issuedAt?: string;
}) {
  return (
    <div className="flex flex-col gap-3" role="list" aria-label={strings.detail.medications}>
      {medications.map((medication, index) => (
        <div
          key={`${medication.name}-${index}`}
          role="listitem"
          className="rounded-xl border border-border bg-surface px-5 py-4"
        >
          <p className="text-[15px] font-medium text-ink">{medication.name}</p>

          <dl className="mt-2 space-y-1.5">
            {medication.dosage && (
              <MedicationRow label={strings.detail.dosage} value={medication.dosage} />
            )}
            {medication.frequency && (
              <MedicationRow label={strings.detail.frequency} value={medication.frequency} />
            )}
            {medication.duration && (
              <MedicationRow label={strings.detail.duration} value={medication.duration} />
            )}
          </dl>
        </div>
      ))}

      {(doctor || issuedAt) && (
        <p className="px-1 text-sm text-ink-muted">
          {[doctor ? `${strings.detail.doctor}: ${doctor}` : null, issuedAt ? `${strings.detail.issuedAt}: ${issuedAt}` : null]
            .filter((part): part is string => part !== null)
            .join(" · ")}
        </p>
      )}
    </div>
  );
}

function MedicationRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-6">
      <dt className="text-sm text-ink-secondary">{label}</dt>
      <dd className="text-right text-[15px] font-medium text-ink">{value}</dd>
    </div>
  );
}