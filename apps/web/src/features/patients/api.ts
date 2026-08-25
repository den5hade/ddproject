import { api, authed } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type PatientResponse = components["schemas"]["PatientResponse"];
export type PersonUpdate = components["schemas"]["PersonUpdate"];

/** GET /patients/me — auto-creates the patient profile server-side on first call. */
export function getMyPatient() {
  return authed(() => api.GET("/api/v1/patients/me"));
}

/** PATCH /patients/me — updates person fields of the current user's patient. */
export function updateMyPerson(body: PersonUpdate) {
  return authed(() => api.PATCH("/api/v1/patients/me", { body }));
}
