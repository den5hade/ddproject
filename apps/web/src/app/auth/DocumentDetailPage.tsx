import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { ProcessingStatus } from "@/features/documents/components/ProcessingStatus";
import { ProcessingSteps } from "@/features/documents/components/Stepper";
import { OriginalViewer } from "@/features/documents/components/OriginalViewer";
import { ExtractionViewer } from "@/features/documents/components/ExtractionViewer";
import {
  useDocumentWithPolling,
  useDownloadUrl,
} from "@/features/documents/hooks";
import { isProcessing } from "@/features/documents/api";
import type { DocumentResponse } from "@/features/documents/api";
import { OverflowMenu, MenuItem } from "@/components/ui/menu";
import { TabPanel, Tabs, TabsList } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/errors";
import { strings } from "@/lib/i18n/strings";
import { formatBytes, formatDateRu } from "@/lib/utils/format";
import { cn } from "@/lib/utils";

/*
 * Document detail (plan §6.6): header + ••• menu (download; delete
 * disabled until BK-4) · processing stepper with polling · tabs
 * Оригинал / Извлечённая информация · four UI states.
 */

export function DocumentDetailPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const query = useDocumentWithPolling(documentId);

  if (!documentId || query.isError) {
    return (
      <DetailMessage
        title={
          query.error instanceof ApiError && query.error.status === 403
            ? strings.detail.noAccessTitle
            : strings.detail.notFoundTitle
        }
      />
    );
  }

  if (query.isPending || !query.data) {
    return <DetailSkeleton />;
  }

  const document = query.data;

  return (
    <div className="flex flex-col gap-8 overflow-hidden">
      <Link
        to="/documents"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-primary underline-offset-4 hover:underline"
      >
        <ArrowLeft size={16} strokeWidth={2} />
        {strings.detail.back}
      </Link>

      <DocumentHeader document={document} />

      {/* Stepper + honest hint while moving (BK-6: workers are stubs today) */}
      {(isProcessing(document.status) ||
        document.status === "completed" ||
        document.status === "failed") && (
        <div className="flex flex-col gap-2">
          <ProcessingSteps status={document.status} />
          {isProcessing(document.status) && (
            <p className="text-sm text-ink-muted">
              {strings.detail.processingHint}
            </p>
          )}
        </div>
      )}

      <Tabs defaultValue="original" className="flex flex-col gap-4">
        <TabsList
          labels={{
            original: strings.detail.tabOriginal,
            extraction: strings.detail.tabExtraction,
          }}
        />
        <TabPanel value="original">
          <OriginalViewer document={document} />
        </TabPanel>
        <TabPanel value="extraction">
          <ExtractionViewer documentId={document.id} />
        </TabPanel>
      </Tabs>
    </div>
  );
}

function DocumentHeader({ document }: { document: DocumentResponse }) {
  const download = useDownloadUrl(document.id);

  const handleDownload = () => {
    if (download.data?.download_url) {
      window.open(download.data.download_url, "_blank", "noopener,noreferrer");
    } else {
      void download.refetch();
    }
  };

  return (
    <header className="relative flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="mb-1.5 flex items-center gap-2.5">
          <ProcessingStatus status={document.status} />
          <span className="text-caption text-ink-muted">
            {document.mime_type.startsWith("image/") ? "Изображение" : "PDF"} ·{" "}
            {formatBytes(document.size_bytes)}
          </span>
        </div>
        <h1 className="overflow-hidden break-all text-[24px] font-semibold leading-tight text-ink lg:text-[28px]">
          {document.title || document.original_filename}
        </h1>
        <p className="mt-1 text-sm text-ink-muted">
          <time dateTime={document.created_at}>
            {formatDateRu(document.created_at)}
          </time>
        </p>
      </div>

      <OverflowMenu label="Действия с документом">
        <MenuItem
          onSelect={handleDownload}
          disabled={download.isPending || download.isError}
        >
          {strings.detail.download}
        </MenuItem>
        <MenuItem disabled disabledReason={strings.detail.deleteSoon}>
          {strings.detail.delete}
        </MenuItem>
      </OverflowMenu>
    </header>
  );
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-8" aria-hidden="true">
      <Skeleton className="h-5 w-40" />
      <div className="space-y-2">
        <Skeleton className="h-6 w-full max-w-md rounded-lg" />
        <Skeleton className="h-4 w-64" />
      </div>
      <Skeleton className="h-8 w-full max-w-xs" />
      <Skeleton className="h-11 w-full max-w-sm rounded-lg" />
      <Skeleton className="h-[420px] w-full rounded-xl" />
    </div>
  );
}

function DetailMessage({ title }: { title: string }) {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 text-center">
      <p className="font-medium text-ink">{title}</p>
      <Link to="/documents" className={cn("text-sm font-medium text-primary underline-offset-4 hover:underline")}>
        {strings.detail.back}
      </Link>
    </div>
  );
}
