import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  apiClient,
  type ApplyResponse,
  type ManifestSelectionChange,
  type ManifestResponse,
  type PlanResponse,
  type SourceCatalogResponse,
  type StatusResponse,
} from "@/api/client";

export const queryKeys = {
  status: ["status"] as const,
  manifest: ["manifest"] as const,
  plan: ["plan"] as const,
  sourceCatalog: (alias: string) => ["source-catalog", alias] as const,
};

export function useStatusQuery() {
  return useQuery<StatusResponse>({
    queryKey: queryKeys.status,
    queryFn: apiClient.getStatus,
  });
}

export function useManifestQuery(enabled = true) {
  return useQuery<ManifestResponse>({
    queryKey: queryKeys.manifest,
    queryFn: apiClient.getManifest,
    enabled,
  });
}

export function usePlanQuery(enabled = true) {
  return useQuery<PlanResponse>({
    queryKey: queryKeys.plan,
    queryFn: apiClient.getPlan,
    enabled,
  });
}

export function useSourceCatalogQuery(alias: string) {
  return useQuery<SourceCatalogResponse>({
    queryKey: queryKeys.sourceCatalog(alias),
    queryFn: () => apiClient.getSourceCatalog(alias),
    enabled: Boolean(alias),
  });
}

export function usePatchManifestMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: ManifestSelectionChange[]) =>
      apiClient.patchManifest(changes),
    onSuccess: async () => {
      toast.success("Manifest updated");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.status }),
        queryClient.invalidateQueries({ queryKey: queryKeys.manifest }),
        queryClient.invalidateQueries({ queryKey: queryKeys.plan }),
        queryClient.invalidateQueries({
          predicate: (query) => query.queryKey[0] === "source-catalog",
        }),
      ]);
    },
    onError: (error) => {
      toast.error(
        error instanceof Error ? error.message : "Failed to update manifest",
      );
    },
  });
}

export function useApplyPlanMutation() {
  const queryClient = useQueryClient();
  return useMutation<ApplyResponse>({
    mutationFn: apiClient.applyPlan,
    onSuccess: async () => {
      toast.success("Apply complete");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.status }),
        queryClient.invalidateQueries({ queryKey: queryKeys.manifest }),
        queryClient.invalidateQueries({ queryKey: queryKeys.plan }),
        queryClient.invalidateQueries({
          predicate: (query) => query.queryKey[0] === "source-catalog",
        }),
      ]);
    },
    onError: (error) => {
      toast.error(
        error instanceof Error ? error.message : "Failed to apply plan",
      );
    },
  });
}
