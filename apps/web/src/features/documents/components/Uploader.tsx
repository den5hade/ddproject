import { useEffect, useRef, useState } from "react";
import { Camera, FolderOpen, X } from "lucide-react";
import type { DragEvent } from "react";
import { useUploader } from "../hooks";
import { UPLOAD_ACCEPT } from "../uploadMachine";
import { strings } from "@/lib/i18n/strings";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/*
 * Documents uploader (plan §6.5, SG §42–43).
 * Mobile: «Добавить» → bottom sheet [Сделать фото][Выбрать файл][Отмена].
 * Desktop: primary button + drag&drop dropzone.
 * One component, responsive behavior. Progress row with cancel.
 */

interface UploaderProps {
  patientId: string;
}

export function Uploader({ patientId }: UploaderProps) {
  const { state, start, cancel } = useUploader(patientId);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const photoInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);

  // Escape closes the bottom sheet
  useEffect(() => {
    if (!sheetOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSheetOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sheetOpen]);

  const pickAndClose = (input: HTMLInputElement | null) => {
    setSheetOpen(false);
    input?.click();
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragOver(false);
    const file = event.dataTransfer.files[0];
    if (file) start(file);
  };

  const uploading = state.status === "uploading";

  return (
    <>
      {/* Header actions */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setSheetOpen(true)}
          disabled={uploading}
          className={cn(buttonVariants({ size: "sm" }), "lg:hidden")}
        >
          <PlusGlyph />
          {strings.documents.add}
        </button>

        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className={cn(buttonVariants({ size: "sm" }), "hidden lg:inline-flex")}
        >
          <PlusGlyph />
          {strings.documents.add}
        </button>
      </div>

      {/* Desktop drag&drop zone (SG §43) */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!uploading) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        data-testid="dropzone"
        className={cn(
          "hidden flex-col items-center gap-1 rounded-xl border border-dashed px-6 py-6 text-center transition-colors duration-150 ease-out lg:flex",
          dragOver ? "border-primary bg-primary-soft" : "border-border-strong bg-surface",
          uploading && "opacity-50",
        )}
      >
        <p className="text-[15px] text-ink-secondary">{strings.documents.dropzoneText}</p>
        <p className="text-sm text-ink-muted">
          {strings.documents.dropzoneOr}{" "}
          <button
            type="button"
            className="font-medium text-primary underline-offset-4 hover:underline disabled:text-ink-disabled"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            {strings.documents.chooseFileShort}
          </button>
        </p>
      </div>

      {/* Upload progress / error row */}
      {(uploading || state.status === "error") && (
        <UploadStatusRow
          state={state}
          onCancel={cancel}
          onRetry={(file) => start(file)}
        />
      )}

      {/* Mobile bottom sheet (SG §42) */}
      {sheetOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="presentation">
          <button
            type="button"
            aria-label="Закрыть"
            className="absolute inset-0 bg-ink/30"
            onClick={() => setSheetOpen(false)}
          />
          <div
            ref={sheetRef}
            role="dialog"
            aria-modal="true"
            aria-label={strings.documents.add}
            className="absolute inset-x-0 bottom-0 rounded-t-2xl border-t border-border bg-surface p-5 pb-8 shadow-[var(--shadow-floating)]"
          >
            <p className="mb-4 text-center text-[15px] font-semibold text-ink">
              {strings.documents.add}
            </p>
            <div className="flex flex-col gap-3">
              <Button onClick={() => pickAndClose(photoInputRef.current)}>
                <Camera size={18} strokeWidth={2} />
                {strings.documents.takePhoto}
              </Button>
              <Button
                variant="secondary"
                onClick={() => pickAndClose(fileInputRef.current)}
              >
                <FolderOpen size={18} strokeWidth={2} />
                {strings.documents.chooseFile}
              </Button>
              <Button variant="ghost" onClick={() => setSheetOpen(false)}>
                {strings.common.cancel}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Hidden inputs */}
      <input
        ref={photoInputRef}
        type="file"
        accept="image/jpeg,image/png,image/tiff"
        capture="environment"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) start(file);
        }}
      />
      <input
        ref={fileInputRef}
        type="file"
        accept={UPLOAD_ACCEPT}
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) start(file);
        }}
      />
    </>
  );
}

function PlusGlyph() {
  return (
    <svg
      aria-hidden="true"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    >
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

function UploadStatusRow({
  state,
  onCancel,
  onRetry,
}: {
  state: ReturnType<typeof useUploader>["state"];
  onCancel: () => void;
  onRetry: (file: File) => void;
}) {
  if (state.status === "error") {
    return (
      <div className="rounded-xl border border-border bg-danger-bg px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-danger">
            {strings.documents.uploadErrorTitle}: {state.message}
          </p>
          {state.file && (
            <button
              type="button"
              className="shrink-0 rounded-lg border border-danger/40 px-2.5 py-1 text-xs font-medium text-danger transition-colors hover:bg-surface"
              onClick={() => onRetry(state.file as File)}
            >
              {strings.documents.retryUpload}
            </button>
          )}
        </div>
      </div>
    );
  }

  if (state.status !== "uploading") return null;

  const fileName =
    state.file.name.length > 28
      ? `${state.file.name.slice(0, 25)}…`
      : state.file.name;

  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-3">
      <div className="flex items-center gap-3">
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">
          {fileName}
        </span>
        <span className="text-sm tabular-nums text-ink-secondary">
          {strings.documents.uploadingPercent(state.progress)}
        </span>
        <button
          type="button"
          aria-label={strings.documents.cancelUpload}
          className="rounded-md p-1 text-ink-secondary transition-colors hover:bg-surface-muted hover:text-ink"
          onClick={onCancel}
        >
          <X size={16} strokeWidth={2} />
        </button>
      </div>
      {/* Progress bar (SG §48: progress for upload) */}
      <div
        role="progressbar"
        aria-valuenow={state.progress}
        aria-valuemin={0}
        aria-valuemax={100}
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-muted"
      >
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-150 ease-out"
          style={{ width: `${state.progress}%` }}
        />
      </div>
    </div>
  );
}
