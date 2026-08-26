import { useRouteError } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { strings } from "@/lib/i18n/strings";

/*
 * Route-level error boundary (M7). Rendered via errorElement on
 * top-level routes — catches render/loader crashes per segment.
 * No PHI is ever logged or displayed.
 */
export function ErrorBoundary() {
  const error = useRouteError();
  // Deliberately not logging to console (M7 hardening): the message may
  // carry user data; users get a calm retry screen instead.
  void error;
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 px-5 text-center">
      <p className="text-lg font-medium text-ink">{strings.common.errorTitle}</p>
      <Button variant="secondary" onClick={() => window.location.reload()}>
        {strings.common.retry}
      </Button>
    </main>
  );
}
