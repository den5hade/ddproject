import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";
import { cn } from "@/lib/utils";

/*
 * SG §21–24: primary h-11 (48px mobile via min-h), secondary bordered,
 * tertiary text-button. Destructive never rendered as red primary.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg font-medium transition-colors duration-150 ease-out disabled:pointer-events-none disabled:text-ink-disabled select-none",
  {
    variants: {
      variant: {
        primary: "bg-primary text-white hover:bg-primary-dark",
        secondary:
          "bg-surface text-ink border border-border-strong hover:bg-surface-muted",
        ghost: "text-ink-secondary hover:bg-surface-muted hover:text-ink",
        link: "text-primary underline-offset-4 hover:underline px-0 h-auto",
      },
      size: {
        default: "h-11 px-5 text-[15px]",
        sm: "h-9 px-3.5 text-sm",
        lg: "h-12 px-6 text-base",
        icon: "h-11 w-11",
      },
    },
    defaultVariants: { variant: "primary", size: "default" },
  },
);

function Button({
  className,
  variant,
  size,
  ...props
}: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants>) {
  return (
    <button
      data-slot="button"
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

/* eslint-disable-next-line react-refresh/only-export-components -- variants export is part of the shadcn component API */
export { Button, buttonVariants };
