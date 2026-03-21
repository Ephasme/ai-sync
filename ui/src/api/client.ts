export type ManifestSection =
  | "agents"
  | "skills"
  | "commands"
  | "rules"
  | "mcp-servers";

export interface ResolvedSource {
  alias: string;
  source: string;
  version: string | null;
  root: string;
  kind: string;
  fingerprint: string;
  portability_warning: string | null;
}

export interface SourceConfig {
  source: string;
  version?: string | null;
}

export interface ProjectManifestData {
  sources: Record<string, SourceConfig>;
  agents: string[];
  skills: string[];
  commands: string[];
  rules: string[];
  "mcp-servers": string[];
  settings: Record<string, unknown>;
}

export interface StatusResponse {
  initialized: boolean;
  workspace_root: string;
  project_root: string | null;
  manifest_path: string | null;
  manifest: ProjectManifestData;
  selections: Record<string, string[]>;
  sources: ResolvedSource[];
}

export interface SourceCatalogEntry {
  kind: string;
  resource_id: string;
  scoped_ref: string;
  name: string;
  description: string;
  selected: boolean;
}

export interface SourceCatalogResponse {
  alias: string;
  entries: SourceCatalogEntry[];
}

export interface ManifestResponse {
  manifest_path: string;
  raw: string;
  manifest: ProjectManifestData;
}

export interface PlanSourceData {
  alias: string;
  source: string;
  version: string | null;
  kind: string;
  fingerprint: string;
  portability_warning?: string | null;
}

export interface PlanActionData {
  action: string;
  source_alias: string;
  kind: string;
  resource: string;
  name: string;
  description: string;
  target: string;
  display_target: string;
  target_key: string;
  client: string;
  secret_backed?: boolean;
}

export interface ApplyPlanData {
  created_at: string;
  project_root: string;
  manifest_path: string;
  manifest_fingerprint: string;
  sources: PlanSourceData[];
  selections: Record<string, string[]>;
  settings: Record<string, unknown>;
  actions: PlanActionData[];
}

export interface PlanResponse {
  plan: ApplyPlanData;
  messages: Array<Record<string, unknown>>;
  warnings: string[];
}

export interface ApplyResponse {
  exit_code: number;
  messages: Array<Record<string, unknown>>;
  warnings: string[];
}

export interface ManifestSelectionChange {
  section: ManifestSection;
  scoped_ref: string;
  enabled: boolean;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}

export const apiClient = {
  getStatus: () => requestJson<StatusResponse>("/status"),
  getSourceCatalog: (alias: string) =>
    requestJson<SourceCatalogResponse>(
      `/sources/${encodeURIComponent(alias)}/catalog`,
    ),
  getManifest: () => requestJson<ManifestResponse>("/manifest"),
  patchManifest: (changes: ManifestSelectionChange[]) =>
    requestJson<ManifestResponse>("/manifest", {
      method: "PATCH",
      body: JSON.stringify({ changes }),
    }),
  getPlan: () => requestJson<PlanResponse>("/plan"),
  applyPlan: () =>
    requestJson<ApplyResponse>("/apply", {
      method: "POST",
    }),
};
