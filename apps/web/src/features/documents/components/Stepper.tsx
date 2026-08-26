import { AlertTriangle, Check } from "lucide-react";
import type { DocumentStatus } from "../api";
import { cn } from "@/lib/utils";

/*
 * Processing stepper (plan §6.6, SG §31–32):
 * Загружен → Обрабатывается → Готов | Требует внимания.
 * Thin line + small dots; slow pulse while processing (SG §32).
 */

type StepTone = "done" | "active" | "pending" | "danger";

interface Step {
  key: string;
  label: string;
  tone: StepTone;
}

export function ProcessingSteps({
  status,
  className,
}: {
  status: DocumentStatus;
  className?: string;
}) {
  const failed = status === "failed" || status === "deleted";
  const steps: Step[] = [
    { key: "uploaded", label: "Загружен", tone: "done" },
    {
      key: "processing",
      label: "Обрабатывается",
      tone:
        status === "completed" || failed
          ? "done"
          : status === "processing"
            ? "active"
            : "pending",
    },
    failed
      ? { key: "result", label: "Требует внимания", tone: "danger" }
      : {
          key: "result",
          label: "Готов",
          tone: status === "completed" ? "done" : "pending",
        },
  ];

  return (
    <ol
      aria-label="Статус обработки"
      className={cn("flex items-center gap-0", className)}
    >
      {steps.map((step, index) => (
        <li key={step.key} className="flex items-center">
          {index > 0 && (
            <span
              aria-hidden="true"
              className={cn(
                "mx-2 h-px w-6 sm:w-10",
                step.tone === "pending" ? "bg-border" : "bg-border-strong",
              )}
            />
          )}
          <span className="flex items-center gap-1.5">
            <StepDot tone={step.tone} />
            <span
              className={cn(
                "text-xs font-medium whitespace-nowrap sm:text-sm",
                step.tone === "active" && "text-info",
                step.tone === "done" && "text-success",
                step.tone === "danger" && "text-danger",
                step.tone === "pending" && "text-ink-muted",
              )}
            >
              {step.label}
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}

function StepDot({ tone }: { tone: StepTone }) {
  if (tone === "active") {
    return (
      <span
        aria-hidden="true"
        className="flex h-5 w-5 items-center justify-center rounded-full bg-info-bg text-[8px] text-info animate-pulse"
      >
        ●●●
      </span>
    );
  }
  if (tone === "done") {
    return (
      <span
        aria-hidden="true"
        className="flex h-5 w-5 items-center justify-center rounded-full bg-success-bg text-success"
      >
        <Check size={11} strokeWidth={2.5} />
      </span>
    );
  }
  if (tone === "danger") {
    return (
      <span
        aria-hidden="true"
        className="flex h-5 w-5 items-center justify-center rounded-full bg-danger-bg text-danger"
      >
        <AlertTriangle size={11} strokeWidth={2.5} />
      </span>
    );
  }
  return (
    <span
      aria-hidden="true"
      className="h-2 w-2 rounded-full border border-border-strong bg-surface"
    />
  );
}
