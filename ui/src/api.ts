// Typed calls to this node's user API (node/api_user.py). Same origin as the dashboard.

export type PeerState = "alive" | "suspect" | "dead";

export interface Peer {
  node_id: string;
  host_id: string;
  addr: string;
  state: PeerState;
  tier: number;
  rtt_ms: number;
  bw_mbps: number;
  free_bytes: number;
  last_ok_s_ago?: number;
  self?: boolean;
}

export interface RepairEvent {
  t: number;
  kind: "copied" | "corrupt_local";
  chunk: string;
  to?: string;
}

export interface Stats {
  node_id: string | null;
  codec: string;
  unlocked: boolean;
  username: string | null;
  peers: Peer[];
  files: { count: number; healthy: number; degraded: number; unavailable: number };
  repair: {
    last_round: Record<string, number> | null;
    total_copies: number;
    events: RepairEvent[];
  };
}

export type FileStatus = "healthy" | "degraded" | "unavailable";

export interface FileEntry {
  file_uuid: string;
  name: string;
  manifest_id: string;
  version: number;
  size: number;
  sha256: string;
  chunks: number;
  status: FileStatus;
}

export interface UploadResult {
  file_uuid: string;
  name: string;
  version: number;
  original_bytes: number;
  encoded_bytes: number;
  sent_bytes: number;
  replicated_bytes: number;
  sent_chunks: number;
  reused_chunks: number;
  status: "durable" | "degraded";
  compression_ratio: number | null;
  chunks: { index: number; chunk_id: string; holders: string[] }[];
}

export interface ChunkMap {
  file_uuid: string;
  status: FileStatus;
  replication: number;
  chunks: {
    index: number;
    chunk_id: string;
    live_hosts: number;
    holders: { node_id: string; state: PeerState | "unknown" }[];
  }[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  stats: () => call<Stats>("/stats"),
  files: () => call<FileEntry[]>("/files"),
  map: (uuid: string) => call<ChunkMap>(`/files/${uuid}/map`),
  recover: (username: string, passphrase: string) =>
    call<{ username: string; files_restored: number; files_unavailable: number; files: FileEntry[] }>("/recover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, passphrase }),
    }),
  upload: (file: File, name: string) =>
    call<UploadResult>(`/files?name=${encodeURIComponent(name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    }),
  downloadUrl: (uuid: string) => `/files/${uuid}`,
};

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 ? 2 : 1)} ${units[i]}`;
}
