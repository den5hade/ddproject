import { useEffect, useRef, useState, type ReactNode } from "react";
import { MoreHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";

/*
 * Minimal ••• menu (SG §24): overflow actions live here, destructive
 * items are plain menu rows + separate confirmation — never red primary.
 */

export function OverflowMenu({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        onClick={() => setOpen((value) => !value)}
        className="flex h-11 w-11 items-center justify-center rounded-lg text-ink-secondary transition-colors duration-150 ease-out hover:bg-surface-muted hover:text-ink"
      >
        <MoreHorizontal size={20} strokeWidth={2} />
      </button>

      {open && (
        <div
          role="menu"
          aria-label={label}
          className="absolute right-0 top-full z-30 mt-1 min-w-[180px] rounded-lg border border-border bg-surface py-1 shadow-[var(--shadow-floating)]"
        >
          {children}
        </div>
      )}
    </div>
  );
}

export function MenuItem({
  children,
  onSelect,
  disabled,
  disabledReason,
}: {
  children: ReactNode;
  onSelect?: () => void;
  disabled?: boolean;
  disabledReason?: string;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      title={disabled ? disabledReason : undefined}
      disabled={disabled}
      onClick={() => {
        if (!disabled) {
          onSelect?.();
        }
      }}
      className={cn(
        "flex w-full items-center px-3.5 py-2.5 text-left text-sm text-ink transition-colors duration-150 ease-out",
        disabled
          ? "cursor-not-allowed text-ink-disabled"
          : "hover:bg-surface-muted",
      )}
    >
      {children}
    </button>
  );
}
