import { Link } from "react-router-dom";
import { useMyPatient } from "@/features/auth/hooks";
import { useMyPatientDocuments } from "@/features/documents/hooks";
import { DocumentList } from "@/features/documents/components/DocumentList";
import { TabPanel, Tabs, TabsList } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { strings } from "@/lib/i18n/strings";
import { pluralYears } from "@/lib/utils/format";

/*
 * Medical record (plan §6.7): read-only for MVP.
 * Обзор — person data + privacy line; Документы — grouped list reuse.
 */

const SEX_LABELS: Record<string, string> = {
  male: strings.profile.sexMale,
  female: strings.profile.sexFemale,
  unspecified: strings.profile.sexUnspecified,
};

export function MedicalRecordPage() {
  const patient = useMyPatient();
  const documents = useMyPatientDocuments(patient.data?.id);
  const person = patient.data?.person;

  const rows: Array<[string, string]> = [
    [strings.profile.name, person?.name?.trim() || "—"],
    [
      strings.profile.age,
      person?.age != null ? pluralYears(person.age) : "—",
    ],
    [strings.profile.sex, person?.sex ? (SEX_LABELS[person.sex] ?? "—") : "—"],
    [strings.profile.city, person?.city?.trim() || "—"],
    [strings.profile.profession, person?.profession?.trim() || "—"],
    [strings.profile.height, person?.height != null ? `${person.height} см` : "—"],
    [strings.profile.weight, person?.weight != null ? `${person.weight} кг` : "—"],
  ];

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="text-[28px] font-semibold leading-tight text-ink lg:text-[30px]">
          {strings.record.title}
        </h1>
        <p className="mt-1 text-[15px] text-ink-secondary">
          {strings.record.subtitle}
        </p>
      </header>

      {patient.isPending ? (
        <OverviewSkeleton />
      ) : (
        <Tabs defaultValue="overview" className="flex flex-col gap-5">
          <TabsList
            labels={{
              overview: strings.record.tabOverview,
              documents: strings.record.tabDocuments,
            }}
          />
          <TabPanel value="overview">
            <dl className="rounded-xl border border-border bg-surface px-5 py-2">
              {rows.map(([label, value]) => (
                <div
                  key={label}
                  className="flex items-baseline justify-between gap-6 border-b border-border py-3.5 last:border-b-0"
                >
                  <dt className="text-sm text-ink-secondary">{label}</dt>
                  <dd className="text-right text-[15px] font-medium text-ink">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>

            <div className="mt-4 flex items-center justify-between gap-4">
              <p className="text-sm text-ink-muted">{strings.common.privacyLine}</p>
              <Link
                to="/profile/edit"
                className="shrink-0 text-sm font-medium text-primary underline-offset-4 hover:underline"
              >
                {strings.record.editInProfile}
              </Link>
            </div>
          </TabPanel>

          <TabPanel value="documents">
            <DocumentList
              documents={documents.data}
              isPending={documents.isPending}
              isError={documents.isError}
              onRetry={() => void documents.refetch()}
              emptyState={
                <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border-strong bg-surface px-6 py-10 text-center">
                  <p className="font-medium text-ink">
                    {strings.dashboard.emptyDocumentsTitle}
                  </p>
                  <p className="max-w-[380px] text-sm leading-relaxed text-ink-secondary">
                    {strings.record.emptyDocumentsText}
                  </p>
                </div>
              }
            />
          </TabPanel>
        </Tabs>
      )}
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-3" aria-hidden="true">
      <Skeleton className="h-[52px] w-full rounded-xl" />
      <Skeleton className="h-[52px] w-full rounded-xl" />
      <Skeleton className="h-[52px] w-full rounded-xl" />
    </div>
  );
}
