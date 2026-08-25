import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import * as authApi from "./api";
import {
  clearSession,
  getRefreshToken,
  hasSession,
  storeTokens,
} from "./session";
import { getMyPatient } from "@/features/patients/api";
import { keys } from "@/lib/query/keys";

/*
 * Auth orchestration: API modules stay pure; hooks own the
 * session side-effects and navigation (plan §5.1).
 */

export function useMe() {
  return useQuery({
    queryKey: keys.me(),
    queryFn: authApi.getMe,
    enabled: hasSession(),
    retry: false,
    staleTime: 60_000,
  });
}

export function useMyPatient() {
  return useQuery({
    queryKey: keys.patientMe(),
    queryFn: getMyPatient,
    enabled: hasSession(),
    retry: false,
    staleTime: 60_000,
  });
}

export function useRequestOtp() {
  return useMutation({ mutationFn: authApi.requestOtp });
}

interface VerifyArgs {
  identity: string;
  code: string;
}

export function useVerifyOtp() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ identity, code }: VerifyArgs) =>
      authApi.verifyOtp({ identity, code }),
    onSuccess: (tokens) => {
      storeTokens(tokens.access_token, tokens.refresh_token);
      // Fresh session: drop anything cached under the previous (anonymous) state
      queryClient.removeQueries({ queryKey: keys.me() });
      queryClient.removeQueries({ queryKey: keys.patientMe() });
      navigate("/", { replace: true });
    },
  });
}

export function useLogout() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const refreshToken = getRefreshToken();
      if (refreshToken) await authApi.logout(refreshToken);
    },
    onSettled: () => {
      clearSession();
      queryClient.clear();
      navigate("/login", { replace: true });
    },
  });
}
