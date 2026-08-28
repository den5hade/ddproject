import { useDownloadUrl } from "../hooks";
import type { DocumentResponse } from "../api";
import { strings } from "@/lib/i18n/strings";
import { cn } from "@/lib/utils";

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

  return (
    <div
      className={cn(
        "flex flex-col items-center gap-4 rounded-xl border border-border bg-surface px-5 py-10 text-center",
        className,
      )}
    >
      <FileGlyph />
      <p className="text-[15px] font-medium text-ink">
        {doc.title || doc.original_filename}
      </p>
      <p className="text-sm text-ink-muted">
        {isImage(doc.mime_type) ? "Изображение" : "PDF"}
      </p>
      <a
        href={url ?? undefined}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          "mt-2 rounded-lg border border-border-strong bg-surface px-5 font-medium text-ink transition-colors duration-150 ease-out hover:bg-surface-muted",
          "flex h-11 items-center text-[15px]",
        )}
        onClick={(event) => {
          if (!url) event.preventDefault();
        }}
      >
        {strings.detail.openDocument}
      </a>
    </div>
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
