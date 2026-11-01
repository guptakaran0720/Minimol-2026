import { useRef, useState } from "react";
import { api, formatBytes, type UploadResult } from "../api";

export function Upload({ onUploaded }: { onUploaded: (r: UploadResult) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<{ result: UploadResult; seconds: number } | null>(null);

  async function send(file: File) {
    setBusy(file.name);
    setError(null);
    const started = performance.now();
    try {
      const result = await api.upload(file, file.name);
      setLast({ result, seconds: (performance.now() - started) / 1000 });
      onUploaded(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
      if (input.current) input.current.value = "";
    }
  }

  const r = last?.result;
  return (
    <section className="card">
      <header className="card-head">
        <h2>Upload</h2>
        <span className="muted">Same name again = new version, only changed chunks are sent</span>
      </header>
      <label className={`drop ${busy ? "busy" : ""}`}>
        <input
          ref={input}
          type="file"
          disabled={!!busy}
          onChange={(e) => e.target.files?.[0] && send(e.target.files[0])}
        />
        {busy ? `Compressing, encrypting and placing ${busy}…` : "Choose a file (max 256 MiB)"}
      </label>
      {error && <p className="error">{error}</p>}
      {r && last && (
        <div className="result">
          <div className="result-title">
            <strong>{r.name}</strong> v{r.version}
            <span className={`badge badge-${r.status === "durable" ? "healthy" : "degraded"}`}>{r.status}</span>
            <span className="muted">{last.seconds.toFixed(2)} s</span>
          </div>
          <dl className="metrics">
            <div>
              <dt>Original</dt>
              <dd>{formatBytes(r.original_bytes)}</dd>
            </div>
            <div>
              <dt>After compression + encryption</dt>
              <dd>
                {formatBytes(r.encoded_bytes)}
                {r.compression_ratio !== null && <span className="muted"> ({(r.compression_ratio * 100).toFixed(1)}%)</span>}
              </dd>
            </div>
            <div>
              <dt>Stored across peers</dt>
              <dd>{formatBytes(r.replicated_bytes)}</dd>
            </div>
            <div>
              <dt>Sent this upload</dt>
              <dd>
                {formatBytes(r.sent_bytes)}
                <span className="muted">
                  {" "}
                  ({r.sent_chunks} sent, {r.reused_chunks} reused)
                </span>
              </dd>
            </div>
          </dl>
        </div>
      )}
    </section>
  );
}
