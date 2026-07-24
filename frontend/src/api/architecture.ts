/** Architecture API client — typed fetch wrappers for architecture endpoints. */

export interface ArchitectureNode {
  id: string;
  type: "service" | "table" | "external" | "endpoint";
  label: string;
  description: string;
  source_file?: string;
  schedule?: string;
  columns?: string[];
  tags?: string[];
}

export interface ArchitectureEdge {
  from: string;
  to: string;
  label: string;
  type: "data_fetch" | "write" | "read" | "stream" | "api" | "read_write";
}

export interface ArchitectureSchema {
  version: string;
  last_updated: string;
  description: string;
  nodes: ArchitectureNode[];
  edges: ArchitectureEdge[];
}

export interface ServiceStatus {
  status?: string;
  last_run?: string;
  completed_at?: string;
  records_processed?: number;
  total_events?: number;
  row_count?: number;
  latest_event?: string;
  active_pairs?: number;
  latest_refresh?: string;
  error?: string;
}

export interface TableStatus {
  row_count?: number;
  error?: string;
}

export interface ArchitectureStatus {
  services: Record<string, ServiceStatus>;
  tables: Record<string, TableStatus>;
}

export async function getArchitectureSchema(): Promise<ArchitectureSchema> {
  const res = await fetch("/api/architecture/schema");
  if (!res.ok) throw new Error(`Get architecture schema failed (${res.status})`);
  return res.json() as Promise<ArchitectureSchema>;
}

export async function getArchitectureStatus(): Promise<ArchitectureStatus> {
  const res = await fetch("/api/architecture/status");
  if (!res.ok) throw new Error(`Get architecture status failed (${res.status})`);
  return res.json() as Promise<ArchitectureStatus>;
}

export async function validateArchitectureSchema(): Promise<{
  valid: boolean;
  missing_files: string[];
  total_nodes: number;
}> {
  const res = await fetch("/api/architecture/validate", { method: "POST" });
  if (!res.ok) throw new Error(`Validate architecture schema failed (${res.status})`);
  return res.json() as Promise<{
    valid: boolean;
    missing_files: string[];
    total_nodes: number;
  }>;
}