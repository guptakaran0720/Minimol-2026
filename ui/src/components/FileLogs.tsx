import { useCallback, useEffect } from "react";
import { api, formatBytes, type FileEntry, type Peer, type TransferEntry } from "../api";
import { usePoll } from "../usePoll";

function clock(t: number): string {
  return new Date(t * 1000).toLocaleTimeString([], { hour12: false });
}

function Mac({ mac }: { mac: string | null | undefined }) {
  return <span className="mono">{mac ?? "—"}</span>;
}

/**
 * The "Logs" panel for one file: where each chunk is stored now, which laptops this
 * laptop uploaded its chunks to, and which laptops it downloaded them from, with the
 * IP and MAC address of each.
 */
export function FileLogs({ file, peers, onClose }: { file: FileEntry; peers: Peer[]; onClose: () => void }) {
  const loadMap = useCallback(() => api.map(file.file_uuid), [file.file_uuid]);
  const map = usePoll(loadMap, 2000, file.file_uuid);
  const ids = map.data ? [...map.data.chunks.map((c) => c.chunk_id), file.manifest_id] : null;
  const loadLog = useCallback(() => api.transfers(ids ?? []), [ids?.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const log = usePoll(loadLog, 2000, ids ? `${file.file_uuid}:${ids.length}` : null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const byId = new Map(peers.map((p) => [p.node_id, p]));
  const indexOf = new Map((map.data?.chunks ?? []).map((c) => [c.chunk_id, c.index]));
  const label = (chunkId: string) => (chunkId === file.manifest_id ? "manifest" : `#${indexOf.get(chunkId) ?? "?"}`);
  const entries = log.data?.transfers ?? [];
  const uploads = entries.filter((e) => e.direction === "upload");
  const downloads = entries.filter((e) => e.direction === "download");

  return (
    <div className="logs-backdrop" onClick={onClose}>
      <section
        className="tile tile-white logs-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="logs-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="tile-head">
          <h2 id="logs-title" className="tile-title">
            Logs · {file.name}
          </h2>
          <button className="text-btn" onClick={onClose} aria-label="Close logs">
            Close
          </button>
        </div>
        <p className="muted small">
          v{file.version} · {formatBytes(file.size)} · {file.chunks} chunk{file.chunks === 1 ? "" : "s"} + manifest
          {file.lock_mac ? (
            <>
              {" "}· locked to <span className="mono">{file.lock_mac}</span>
              {file.locked_here === false ? " (not this laptop)" : " (this laptop)"}
            </>
          ) : (
            " · not locked"
          )}
        </p>

        <h3 className="logs-h">Stored on now</h3>
        <div className="table-wrap">
          <table className="peers logs-table">
            <thead>
              <tr>
                <th scope="col">Chunk</th>
                <th scope="col">Laptop</th>
                <th scope="col">IP address</th>
                <th scope="col">MAC address</th>
                <th scope="col">State</th>
              </tr>
            </thead>
            <tbody>
              {(map.data?.chunks ?? []).flatMap((c) =>
                c.holders.map((h, i) => (
                  <tr key={`${c.chunk_id}-${h.node_id}`}>
                    <td className="mono">{i === 0 ? `#${c.index}` : ""}</td>
                    <td className="mono">{h.node_id}</td>
                    <td className="mono">{byId.get(h.node_id)?.ip ?? "—"}</td>
                    <td>
                      <Mac mac={byId.get(h.node_id)?.mac} />
                    </td>
                    <td>
                      <span className={`badge badge-${h.state === "unknown" ? "dead" : h.state}`}>{h.state}</span>
                    </td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>

        <TransferTable
          title="Uploaded from this laptop to"
          empty="No uploads of this file from this laptop since its node started."
          rows={uploads}
          label={label}
        />
        <TransferTable
          title="Downloaded to this laptop from"
          empty="Not downloaded on this laptop since its node started. Use the download button, then check back."
          rows={downloads}
          label={label}
        />
        <p className="muted small">
          This log lists the transfers made by this laptop's node, including repair copies; other laptops keep their
          own. A laptop's IP and MAC come from its signed heartbeat.
        </p>
      </section>
    </div>
  );
}

function TransferTable({
  title,
  empty,
  rows,
  label,
}: {
  title: string;
  empty: string;
  rows: TransferEntry[];
  label: (chunkId: string) => string;
}) {
  return (
    <>
      <h3 className="logs-h">
        {title} <span className="muted small">({rows.length})</span>
      </h3>
      {rows.length === 0 ? (
        <p className="empty">{empty}</p>
      ) : (
        <div className="table-wrap">
          <table className="peers logs-table">
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Chunk</th>
                <th scope="col">Laptop</th>
                <th scope="col">IP address</th>
                <th scope="col">MAC address</th>
                <th scope="col" className="num">
                  Size
                </th>
                <th scope="col" className="num">
                  Took
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.seq}>
                  <td className="mono">{clock(e.t)}</td>
                  <td className="mono">{label(e.chunk_id)}</td>
                  <td className="mono">{e.node_id}</td>
                  <td className="mono">{e.ip}</td>
                  <td>
                    <Mac mac={e.mac} />
                  </td>
                  <td className="num">{formatBytes(e.bytes)}</td>
                  <td className="num">{e.ms.toFixed(0)} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
