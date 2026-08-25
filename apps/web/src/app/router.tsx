import { createBrowserRouter } from "react-router-dom";

/*
 * Route tree per IMPLEMENTATION_PLAN.md §6.
 * Guards are wired in M2 (auth milestone); placeholder pages for now.
 */
export const router = createBrowserRouter([
  {
    path: "/login",
    lazy: async () => {
      const { LoginPage } = await import("./public/LoginPage");
      return { Component: LoginPage };
    },
  },
  {
    path: "/login/verify",
    lazy: async () => {
      const { VerifyPage } = await import("./public/VerifyPage");
      return { Component: VerifyPage };
    },
  },
  {
    path: "/",
    lazy: async () => {
      const { AuthLayout } = await import("./auth/layout");
      return { Component: AuthLayout };
    },
    children: [
      {
        index: true,
        lazy: async () => {
          const { DashboardPage } = await import("./auth/DashboardPage");
          return { Component: DashboardPage };
        },
      },
      {
        path: "documents",
        lazy: async () => {
          const { DocumentsPage } = await import("./auth/DocumentsPage");
          return { Component: DocumentsPage };
        },
      },
      {
        path: "documents/:documentId",
        lazy: async () => {
          const { DocumentDetailPage } = await import(
            "./auth/DocumentDetailPage"
          );
          return { Component: DocumentDetailPage };
        },
      },
      {
        path: "medical-record",
        lazy: async () => {
          const { MedicalRecordPage } = await import(
            "./auth/MedicalRecordPage"
          );
          return { Component: MedicalRecordPage };
        },
      },
      {
        path: "profile",
        lazy: async () => {
          const { ProfilePage } = await import("./auth/ProfilePage");
          return { Component: ProfilePage };
        },
      },
    ],
  },
]);
