import type * as React from "react";
import { cn } from "@/lib/utils";

/* SG §11: labels weight 500; SG §13: label → input spacing 8px handled by consumer */
function Label({ className, ...props }: React.ComponentProps<"label">) {
  return (
    <label
      data-slot="label"
      className={cn(
        "text-sm font-medium text-ink select-none peer-disabled:text-ink-disabled",
        className,
      )}
      {...props}
    />
  );
}

export { Label };
