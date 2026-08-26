import { AlertTriangle, Check, Clock } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { DocumentStatus } from "../api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/*
 * Processing status chip (SG §31): honest four-state wording,
 * color always paired with icon + text (SG §6).
 * Processing uses a very slow dots pulse — no spinners (SG §32).
 */

const STATUS_META: Record<
  DocumentStatus,
  { label: string; tone: "neutral" | "info" | "success" | "danger"; icon: LucideIcon }
> = {
  pending: { label: "Загружен", tone: "neutral", icon: Clock },
  uploaded: { label: "Загружен", tone: "neutral", icon: Clock },
  processing: { label: "Обрабатывается", tone: "info", icon: Clock },
  completed: { label: "Готов", tone: "success", icon: Check },
  failed: { label: "Требует внимания", tone: "danger", icon: AlertTriangle },
  deleted: { label: "Требует внимания", tone: "danger", icon: AlertTriangle },
};

export function ProcessingStatus({
  status,
  className,
}: {
  status: DocumentStatus;
  className?: string;
}) {
  const meta = STATUS_META[status] ?? STATUS_META.pending;
  const Icon = meta.icon;
  return (
    <Badge tone={meta.tone} className={cn("gap-1.5", className)}>
      {status === "processing" ? (
        <span aria-hidden="true" className="animate-pulse tracking-tight">
          ●●●
        </span>
      ) : (
        <Icon size={12} strokeWidth={2} />
      )}
      {meta.label}
    </Badge>
  );
}
