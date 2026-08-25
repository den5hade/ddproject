import type * as React from "react";
import { cn } from "@/lib/utils";

/* SG §48: skeletons for content loading; spinners only for micro-actions */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-surface-muted", className)}
      {...props}
    />
  );
}

export { Skeleton };
