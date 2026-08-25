import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";
import { cn } from "@/lib/utils";

/*
 * SG §6: status color never alone — consumer must pair badge with
 * text label. Soft backgrounds, desaturated foregrounds.
 */
const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "border-border bg-surface-muted text-ink-secondary",
        success: "border-transparent bg-success-bg text-success",
        warning: "border-transparent bg-warning-bg text-warning",
        danger: "border-transparent bg-danger-bg text-danger",
        info: "border-transparent bg-info-bg text-info",
        accent: "border-transparent bg-primary-soft text-primary-dark",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

function Badge({
  className,
  tone,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return (
    <span
      data-slot="badge"
      className={cn(badgeVariants({ tone }), className)}
      {...props}
    />
  );
}

/* eslint-disable-next-line react-refresh/only-export-components -- variants export is part of the shadcn component API */
export { Badge, badgeVariants };
