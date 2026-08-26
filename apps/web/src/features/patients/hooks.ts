import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "./api";
import type { PersonUpdate } from "./api";
import { keys } from "@/lib/query/keys";

export type { PersonUpdate };

/**
 * PATCH /patients/me → invalidate ["patient","me"] (plan §5.3).
 * The query itself (useMyPatient) lives in features/auth/hooks and
 * shares the bootstrap gate cache — same key, single source.
 */
export function useUpdateMyPerson() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PersonUpdate) => api.updateMyPerson(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.patientMe() });
    },
  });
}
