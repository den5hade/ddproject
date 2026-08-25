import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { RouterProvider } from "react-router-dom";
import { router } from "@/app/router";

/*
 * Providers only (plan §3). No medical/domain components here.
 * SG §49: toasts sparse — success confirmations only.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) => {
        const status = (error as { status?: number }).status;
        if (status && status >= 400 && status < 500) return false;
        return failureCount < 2;
      },
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster position="top-center" duration={3000} />
    </QueryClientProvider>
  );
}

export default App;
