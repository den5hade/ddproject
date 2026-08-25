import type * as React from "react";
import { cn } from "@/lib/utils";

/* SG §25: height 44–48px (h-11), border #D9DEDA, subtle primary focus ring */
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "flex h-11 w-full rounded-lg border border-border-input bg-surface px-3.5 text-[15px] text-ink transition-colors duration-150 ease-out",
        "placeholder:text-ink-disabled",
        "focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20",
        "disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-ink-disabled",
        "aria-invalid:border-danger aria-invalid:focus-visible:ring-danger/20",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
