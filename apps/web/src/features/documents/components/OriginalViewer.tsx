import { useDownloadUrl } from "../hooks";
import type { DocumentResponse } from "../api";
import { Skeleton } from "@/components/ui/skeleton";
import { strings } from "@/lib/i18n/strings";
import { cn } from "@/lib/utils";

/*
 * Original viewer (plan §6.6, decision D9): native <object> for PDF,
 * <img> for images. Mobile fallback per SG §40: preview box + 
 * «Открыть документ» button instead of an inline heavy viewer.
 */

function isImage(mime: string): boolean {
  return mime.startsWith("image/");
}

export function OriginalViewer({
  document: doc,
  className,
}: {
  document: DocumentResponse;
  className?: string;
}) {
  const download = useDownloadUrl(doc.id);
  const url = download.data?.download_url;

  if (download.isPending) {
    return <Skeleton className={cn("h-[420px] w-full rounded-xl", className)} />;
  }

  if (download.isError || !url) {
    return (
      <div className="rounded-xl border border-border bg-surface px-5 py-8 text-center">
        <p className="text-[15px] text-ink-secondary">
          Предпросмотр недоступен
        </p>
        <OpenButton url={null} documentId={doc.id} retry={() => void download.refetch()} />
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      {/* Inline preview — desktop-first; on small screens it stays but
          compact, with the explicit open button below (SG §40) */}
      {isImage(doc.mime_type) ? (
        <img
          src={url}
          alt={doc.title || doc.original_filename}
          loading="lazy"
          className="max-h-[70vh] w-full rounded-xl border border-border bg-surface object-contain"
        />
      ) : (
        <object
          data={`${url}#toolbar=0`}
          type={doc.mime_type}
          aria-label={doc.title || doc.original_filename}
          className="h-[70vh] w-full rounded-xl border border-border bg-surface"
        >
          <PreviewFallback documentId={doc.id} />
        </object>
      )}
      <OpenButton url={url} documentId={doc.id} />
    </div>
  );
}

function PreviewFallback({ documentId }: { documentId: string }) {
  // Browser cannot inline-render the PDF (mobile browsers mostly)
  void documentId;
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <FileGlyph />
      <p className="text-[15px] text-ink-secondary">
        Предпросмотр недоступен в этом браузере
      </p>
      <OpenButton url={null} documentId="" />
    </div>
  );
}

function OpenButton({
  url,
  documentId,
  retry,
}: {
  url: string | null;
  documentId: string;
  retry?: () => void;
}) {
  void documentId;
  if (!url && retry) {
    return (
      <button
        type="button"
        onClick={retry}
        className="mx-auto text-sm font-medium text-primary underline-offset-4 hover:underline"
      >
        {strings.common.retry}
      </button>
    );
  }
  return (
    <a
      href={url ?? undefined}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        "mx-auto rounded-lg border border-border-strong bg-surface px-5 font-medium text-ink transition-colors duration-150 ease-out hover:bg-surface-muted",
        "flex h-11 items-center text-[15px]",
      )}
      onClick={(event) => {
        if (!url) event.preventDefault();
      }}
    >
      {strings.detail.openDocument}
    </a>
  );
}

function FileGlyph() {
  return (
    <svg
      aria-hidden="true"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="text-ink-muted"
    >
      <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
      <path d="M14 2v4a2 2 0 0 0 2 2h4" />
    </svg>
  );
}
