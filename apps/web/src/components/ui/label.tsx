import { forwardRef, type ComponentProps } from "react";
import { cn } from "@/lib/utils";

/* SG §11: labels weight 500; SG §13: label → input spacing 8px handled by consumer */
export const Label = forwardRef<HTMLLabelElement, ComponentProps<"label">>(
  function Label({ className, ...props }, ref) {
    return (
      <label
        ref={ref}
        data-slot="label"
        className={cn(
          "text-sm font-medium text-ink select-none peer-disabled:text-ink-disabled",
          className,
        )}
        {...props}
      />
    );
  },
);
