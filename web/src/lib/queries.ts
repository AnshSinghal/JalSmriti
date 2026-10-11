import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Activity, Area, AreaManifest, Dossier, Evidence, Forecast, Job, Lake, LakeRow, Me, Nearby, News, RtiRequest, WaterReport } from "./types";

export function useAreas() {
  return useQuery({ queryKey: ["areas"], queryFn: () => api.get<{ areas: Area[] }>("/v1/areas").then((r) => r.areas), staleTime: 60_000 });
}

export function useManifest(area?: Area | null) {
  return useQuery({
    queryKey: ["manifest", area?.id, area?.manifest],
    enabled: !!area?.manifest,
    queryFn: async () => {
      const r = await fetch(area!.manifest!);
      if (!r.ok) throw new Error("manifest");
      return (await r.json()) as AreaManifest;
    },
    staleTime: 5 * 60_000,
  });
}

export function useAreaLakes(areaId?: string) {
  return useQuery({
    queryKey: ["lakes", areaId], enabled: !!areaId,
    queryFn: () => api.get<{ lakes: LakeRow[] }>(`/v1/areas/${areaId}/lakes`).then((r) => r.lakes), staleTime: 60_000,
  });
}

export function useLake(id?: string) {
  return useQuery({ queryKey: ["lake", id], enabled: !!id, queryFn: () => api.get<Lake>(`/v1/lakes/${id}`), retry: 1 });
}

export function useEvidence(id?: string, poll = false) {
  return useQuery({
    queryKey: ["evidence", id], enabled: !!id,
    queryFn: () => api.get<{ evidence: Evidence[] }>(`/v1/lakes/${id}/evidence`).then((r) => r.evidence),
    refetchInterval: poll ? 4000 : false,
  });
}

export function useLakeDossiers(id?: string) {
  return useQuery({ queryKey: ["dossiers", id], enabled: !!id, queryFn: () => api.get<{ dossiers: Dossier[] }>(`/v1/lakes/${id}/dossiers`).then((r) => r.dossiers) });
}

export function useLedger(id?: string) {
  return useQuery({ queryKey: ["ledger", id], enabled: !!id, queryFn: () => api.get<{ entries: any[]; verification: { ok: boolean; entries: number; brokenAt?: number } }>(`/v1/lakes/${id}/ledger`) });
}

export function useJob(id?: string | null) {
  return useQuery({
    queryKey: ["job", id], enabled: !!id,
    queryFn: () => api.get<Job>(`/v1/jobs/${id}`),
    refetchInterval: (q) => (q.state.data?.status === "running" || !q.state.data ? 2500 : false),
  });
}

export function useDossier(id?: string) {
  return useQuery({
    queryKey: ["dossier", id], enabled: !!id,
    queryFn: () => api.get<Dossier>(`/v1/dossiers/${id}`),
    refetchInterval: (q) => (q.state.data?.status === "drafting" ? 3000 : false),
  });
}

export function useStats() {
  return useQuery({ queryKey: ["stats"], queryFn: () => api.get<any>("/v1/stats"), staleTime: 60_000 });
}

export function useMe(enabled: boolean) {
  return useQuery({ queryKey: ["me"], enabled, queryFn: () => api.sget<Me>("/v1/secure/me"), staleTime: 60_000, retry: 0 });
}

export function useActivity(enabled: boolean) {
  return useQuery({ queryKey: ["activity"], enabled, queryFn: () => api.sget<Activity>("/v1/secure/me/activity"), staleTime: 30_000 });
}

export function useForecast(lat?: number, lon?: number) {
  return useQuery({
    queryKey: ["forecast", lat?.toFixed(2), lon?.toFixed(2)], enabled: lat != null && lon != null,
    queryFn: () => api.get<Forecast>(`/v1/forecast?lat=${lat}&lon=${lon}`), staleTime: 15 * 60_000, retry: 1,
  });
}

export function useNearby(lat?: number, lon?: number) {
  return useQuery({
    queryKey: ["nearby", lat?.toFixed(4), lon?.toFixed(4)], enabled: lat != null && lon != null,
    queryFn: () => api.get<Nearby>(`/v1/waterlogging/near?lat=${lat}&lon=${lon}&radius=1000&days=365`), staleTime: 60_000,
  });
}

export function useWaterReports(hours: number) {
  return useQuery({
    queryKey: ["water", hours],
    queryFn: () => api.get<{ hours: number; reports: WaterReport[] }>(`/v1/waterlogging?hours=${hours}`).then((r) => r.reports),
    refetchInterval: 60_000,
  });
}

export function useLakeRti(id?: string) {
  return useQuery({ queryKey: ["rti", id], enabled: !!id, queryFn: () => api.get<{ requests: RtiRequest[] }>(`/v1/lakes/${id}/rti`).then((r) => r.requests) });
}

/** Recent news naming a lake (GDELT, last three months); cached by the API for 12 hours. */
export function useLakeNews(id?: string) {
  return useQuery({ queryKey: ["news", "lake", id], enabled: !!id, queryFn: () => api.get<News>(`/v1/lakes/${id}/news`),
    staleTime: 30 * 60_000, retry: 0 });
}

/** Recent news of flooding at a locality (GDELT, last three months). */
export function useFloodNews(locality?: string | null) {
  return useQuery({ queryKey: ["news", "floods", locality], enabled: !!locality && locality.length >= 4,
    queryFn: () => api.get<News>(`/v1/news/floods?locality=${encodeURIComponent(locality!)}`), staleTime: 30 * 60_000, retry: 0 });
}
