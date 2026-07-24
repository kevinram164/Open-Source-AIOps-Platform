export type ImpactScope = {
  namespaces?: string[];
  workloads?: string[];
  pods?: string[];
  nodes?: string[];
  blast_radius?: string | null;
};

export type ChatResponse = {
  intent?: string | null;
  answer: string;
  evidence: string[];
  recommendation: string | null;
  symptom?: string | null;
  symptom_confidence?: number | null;
  probable_root_cause: string | null;
  root_cause_confidence?: number | null;
  confidence: number | null;
  error_subtype?: string | null;
  impact_scope?: ImpactScope | null;
  incident: {
    id: string | null;
    external_id: string;
    title: string;
    namespace: string | null;
    workload: string | null;
    status: string;
  } | null;
  nba: unknown;
  remediations: Remediation[];
  ops_snapshot?: {
    mode?: string;
    summary?: Record<string, unknown>;
    metrics_source?: string;
    top_cpu_pods?: unknown[];
    top_memory_pods?: unknown[];
    node_usage?: unknown[];
    counts?: Record<string, number>;
    highlights?: string[];
    noteworthy?: string[];
    crashloop_count?: number;
    imagepull_count?: number;
    oom_count?: number;
    nodes?: unknown[];
    warnings?: string[];
    facts_keys?: string[];
    topic?: string;
  } | null;
  model: string | null;
};

export type Incident = {
  id: string;
  external_id: string;
  title: string;
  status: string;
  severity: string;
  namespace: string | null;
  workload: string | null;
  created_at: string;
};

export type Remediation = {
  id: string;
  incident_id: string | null;
  action: string;
  namespace: string;
  target: string;
  parameters: Record<string, unknown>;
  status: string;
  reason: string | null;
  requested_by: string;
  approved_by: string | null;
  result: string | null;
  error: string | null;
  created_at: string;
};

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text.slice(0, 300) || res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function askChat(question: string, namespace?: string): Promise<ChatResponse> {
  return json(
    await fetch("/api/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, namespace: namespace || undefined, auto_analyze: true }),
    }),
  );
}

export async function listIncidents(): Promise<Incident[]> {
  return json(await fetch("/api/v1/incidents?limit=50"));
}

export async function listRemediations(): Promise<Remediation[]> {
  return json(await fetch("/api/v1/remediations"));
}

export async function approveRemediation(id: string, approvedBy = "demo-ui"): Promise<Remediation> {
  return json(
    await fetch(`/api/v1/remediations/${id}/approve?approved_by=${encodeURIComponent(approvedBy)}`, {
      method: "POST",
    }),
  );
}

export async function executeRemediation(id: string): Promise<Remediation> {
  return json(await fetch(`/api/v1/remediations/${id}/execute`, { method: "POST" }));
}
