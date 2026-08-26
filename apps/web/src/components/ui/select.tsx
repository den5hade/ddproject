import { forwardRef, type ComponentProps } from "react";
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
