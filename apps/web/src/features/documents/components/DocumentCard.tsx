import { Link } from "react-router-dom";
import { ChevronRight, FileText, ImageIcon } from "lucide-react";
import type { DocumentResponse } from "../api";
import { ProcessingStatus } from "./ProcessingStatus";
import { formatDateShortRu } from "@/lib/utils/format";
import { cn } from "@/lib/utils";

/*
 * Minimal document card (SG §17–18): type tag, title, date,
 * status chip + chevron. Border separation only, no shadow.
 * The whole card is one link target.
 */

function isImage(mime: string): boolean {
  return mime.startsWith("image/");
}

interface DocumentCardProps {
  document: DocumentResponse;
  to?: string;
}

export function DocumentCard({ document, to }: DocumentCardProps) {
  const href = to ?? `/documents/${document.id}`;
  return (
    <Link
      to={href}
      className={cn(
        "flex items-center gap-4 rounded-xl border border-border bg-surface px-4 py-3.5",
        "transition-colors duration-150 ease-out hover:bg-surface-muted",
      )}
    >
      <span
        aria-hidden="true"
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-ink-secondary"
      >
        {isImage(document.mime_type) ? (
          <ImageIcon size={18} strokeWidth={2} />
        ) : (
          <FileText size={18} strokeWidth={2} />
        )}
      </span>

      <span className="min-w-0 flex-1">
        <span className="block truncate text-[15px] font-medium text-ink">
          {document.title || document.original_filename}
        </span>
        <span className="mt-0.5 flex items-center gap-2 text-caption text-ink-muted">
          <span>{isImage(document.mime_type) ? "Изображение" : "PDF"}</span>
          <span aria-hidden="true">·</span>
          <time dateTime={document.created_at}>
            {formatDateShortRu(document.created_at)}
          </time>
        </span>
      </span>

      <ProcessingStatus status={document.status} />
      <ChevronRight size={16} strokeWidth={2} className="shrink-0 text-ink-muted" />
    </Link>
  );
}
