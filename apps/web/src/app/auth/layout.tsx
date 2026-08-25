import { Outlet } from "react-router-dom";

/* Placeholder — replaced in M3 with real AppShell (bottom nav / sidebar) */
export function AuthLayout() {
  return (
    <main className="mx-auto w-full max-w-[720px] px-5 py-8">
      <Outlet />
    </main>
  );
}
