import {
  forwardRef,
  useEffect,
  useRef,
  useState,
  type ComponentProps,
} from "react";
import { cn } from "@/lib/utils";

/* Native select styled to match Input (h-11, same border/focus ring). */
export const Select = forwardRef<HTMLSelectElement, ComponentProps<"select">>(
  function Select({ className, children, ...props }, ref) {
    return (
      <div className="relative">
        <select
          ref={ref}
          data-slot="select"
          className={cn(
            "flex h-11 w-full appearance-none rounded-lg border border-border-input bg-surface px-3.5 pr-9 text-[15px] text-ink transition-colors duration-150 ease-out",
            "focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20",
            "disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-ink-disabled",
            "aria-invalid:border-danger aria-invalid:focus-visible:ring-danger/20",
            className,
          )}
          {...props}
        >
          {children}
        </select>
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </div>
    );
  },
);

export interface SelectOption {
  value: string;
  label: string;
}

interface SelectDropdownProps {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  /** Shown when no option matches `value`. */
  placeholder?: string;
  disabled?: boolean;
  label: string;
  /** Optional id — wire a <label htmlFor> to the trigger button. */
  id?: string;
}

/*
 * Accessible single-select dropdown (replaces native <select> where its
 * rendering misbehaves, e.g. iOS backdrop-filter moving the popup to the
 * viewport origin). Reuses the OverflowMenu interaction pattern
 * (menu.tsx): an absolutely-positioned listbox below the trigger —
 * never a native element whose popup the browser positions blindly.
 */
export function SelectDropdown({
  value,
  options,
  onChange,
  placeholder,
  disabled,
  label,
  id,
}: SelectDropdownProps) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(() =>
    Math.max(0, options.findIndex((option) => option.value === value)),
  );
  const rootRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const selected = options.find((option) => option.value === value);
  const showPlaceholder = !selected;
  const activeId = open ? `${label.replace(/\s+/g, "-")}-sb-active` : undefined;

  // Keep the highlighted option scrolled into view (hidden by default if
  // the list is closed, so this also helps keyboard-only users).
  useEffect(() => {
    const active = listRef.current?.querySelector<HTMLElement>(
      '[role="option"][aria-selected="true"]',
    );
    active?.scrollIntoView?.({ block: "nearest" });
  }, []);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      const isTargetingRoot =
        event.target instanceof Node && rootRef.current?.contains(event.target);
      if (event.key === "Escape") {
        setOpen(false);
      } else if (
        open &&
        isTargetingRoot &&
        (event.key === "ArrowDown" || event.key === "ArrowUp")
      ) {
        event.preventDefault();
        const direction = event.key === "ArrowDown" ? 1 : -1;
        setHighlight((i) => {
          const next = (i + direction + options.length) % options.length;
          listRef.current
            ?.querySelector<HTMLElement>(
              `[role="option"][data-value="${options[next].value}"]`,
            )
            ?.focus();
          return next;
        });
      } else if (open && isTargetingRoot && (event.key === "Enter" || event.key === " ")) {
        const current = options[highlight];
        if (current) {
          event.preventDefault();
          onChange(current.value);
          setOpen(false);
        }
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, highlight, options, onChange]);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        id={id}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? `${label.replace(/\s+/g, "-")}-sb` : undefined}
        aria-label={id ? undefined : label}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          "flex h-11 w-full items-center justify-between gap-2 rounded-lg border border-border-input bg-surface px-3.5 text-[15px] transition-colors duration-150 ease-out",
          "focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20",
          "disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-ink-disabled",
          open && "border-primary ring-2 ring-primary/20",
          showPlaceholder ? "text-ink-muted" : "text-ink",
        )}
      >
        <span className="truncate text-left">
          {showPlaceholder ? placeholder : selected?.label}
        </span>
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={cn(
            "h-4 w-4 shrink-0 text-ink-muted transition-transform duration-150 ease-out",
            open && "rotate-180",
          )}
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div
          ref={listRef}
          id={`${label.replace(/\s+/g, "-")}-sb`}
          role="listbox"
          aria-label={label}
          aria-activedescendant={activeId}
          className="absolute left-0 right-0 top-full z-30 mt-1 max-h-60 overflow-auto rounded-lg border border-border bg-surface py-1 shadow-[var(--shadow-floating)]"
        >
          {options.map((option, index) => {
            const isSelected = option.value === value;
            const isActive = index === highlight;
            return (
              <button
                type="button"
                key={option.value}
                id={isActive ? activeId : undefined}
                role="option"
                aria-selected={isSelected}
                data-value={option.value}
                tabIndex={-1}
                onPointerEnter={() => setHighlight(index)}
                onClick={() => {
                  onChange(option.value);
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full items-center justify-between px-3.5 py-2.5 text-left text-sm transition-colors duration-150 ease-out",
                  isActive ? "bg-surface-muted text-ink" : "text-ink",
                )}
              >
                <span>{option.label}</span>
                {isSelected && (
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="h-4 w-4 text-primary"
                  >
                    <path d="M20 6 9 17l-5-5" />
                  </svg>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
