import { useRef, useState, type DragEvent } from "react";
import { api, formatBytes, type UploadResult } from "../api";
import { squeeze } from "../feed";

const MAX_BYTES = 256 * 1024 * 1024;

/** The big blue tile: drop or choose a file; shows what the last upload did. */
export function Upload({ onUploaded }: { onUploaded: (r: UploadResult) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<{ result: UploadResult; seconds: number; locked: boolean } | null>(null);
  const [lock, setLock] = useState(false);

  async function send(file: File) {
    if (busy) return;
    if (file.size > MAX_BYTES) {
      setError(`${file.name} is ${formatBytes(file.size)}; the limit is 256 MiB.`);
      return;
    }
    setBusy(file.name);
    setError(null);
    const started = performance.now();
    try {
      const result = await api.upload(file, file.name, lock);
      setLast({ result, seconds: (performance.now() - started) / 1000, locked: lock });
      onUploaded(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
      if (input.current) input.current.value = "";
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) send(file);
  }

  const r = last?.result;
  return (
    <section className="tile tile-blue tile-upload s5 r2" aria-labelledby="upload-title">
      <span className="pill pill-white">Upload</span>
      <label
        className={`drop ${dragging ? "dragging" : ""} ${busy ? "busy" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          ref={input}
          type="file"
          className="visually-hidden"
          disabled={!!busy}
          onChange={(e) => e.target.files?.[0] && send(e.target.files[0])}
        />
        <span className="drop-icon" aria-hidden="true">
          <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 19V5M6 11l6-6 6 6" />
          </svg>
        </span>
        <span id="upload-title" className="drop-title">
          {busy ? (
            <>
              Loading
              <br />
              <span className="drop-name">{busy}</span>
            </>
          ) : (
            <span className="arc-blink">
              Insert
              <br />
              file
            </span>
          )}
        </span>
        <span className="drop-hint">
          {busy
            ? "Compressing, encrypting and placing each chunk on 3 laptops…"
            : "Drop it here or click. Compressed and encrypted on this laptop, then kept on 3 laptops. Same name again = new version; only changed chunks are sent. Max 256 MiB."}
        </span>
        {busy && <span className="progress" aria-hidden="true" />}
      </label>

      <label className="lock-toggle">
        <input type="checkbox" checked={lock} disabled={!!busy} onChange={(e) => setLock(e.target.checked)} />
        <span>
          <strong>Lock to this laptop.</strong> Only this device (by its MAC address) can download or replace the
          file, even with the same username and passphrase.
        </span>
      </label>

      {error && (
        <p className="tile-note tile-note-error" role="alert">
          {error}
        </p>
      )}

      {r && last && !busy && (
        <div className="tile-note result" aria-live="polite">
          <div className="result-title">
            <strong>{r.name}</strong>
            <span className="muted">v{r.version}</span>
            <span className={`badge badge-${r.status === "durable" ? "healthy" : "degraded"}`}>{r.status}</span>
            {last.locked && <span className="badge badge-locked">locked to this laptop</span>}
            <span className="muted">{last.seconds.toFixed(2)} s</span>
          </div>
          <dl className="result-grid">
            <div>
              <dt>Original</dt>
              <dd>{formatBytes(r.original_bytes)}</dd>
            </div>
            <div>
              <dt>Compressed + encrypted</dt>
              <dd>
                {formatBytes(r.encoded_bytes)} <span className="muted">· {squeeze(r.original_bytes, r.encoded_bytes)}</span>
              </dd>
            </div>
            <div>
              <dt>Stored across peers</dt>
              <dd>{formatBytes(r.replicated_bytes)}</dd>
            </div>
            <div>
              <dt>Sent this upload</dt>
              <dd>
                {formatBytes(r.sent_bytes)}{" "}
                <span className="muted">
                  · {r.sent_chunks} sent, {r.reused_chunks} reused
                </span>
              </dd>
            </div>
          </dl>
        </div>
      )}
    </section>
  );
}
