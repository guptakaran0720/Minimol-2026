import { useEffect, useRef, useState } from "react";
import { api, formatBytes, type FileEntry } from "../api";

type Kind = "image" | "pdf" | "video" | "audio" | "text" | "none";

const EXT: Record<string, Kind> = {
  png: "image", jpg: "image", jpeg: "image", gif: "image", webp: "image", bmp: "image",
  pdf: "pdf",
  mp4: "video", webm: "video", mov: "video",
  mp3: "audio", wav: "audio", ogg: "audio", m4a: "audio",
  txt: "text", csv: "text", md: "text", json: "text", log: "text", py: "text", ts: "text", js: "text",
  html: "text", xml: "text", svg: "text", yaml: "text", yml: "text",
};

const TEXT_LIMIT = 200_000; // characters shown; the rest stays a download

export function previewKind(name: string): Kind {
  return EXT[name.split(".").pop()?.toLowerCase() ?? ""] ?? "none";
}

/** Full-screen preview. The node checks every chunk and the whole-file SHA-256 before it
 *  serves the bytes, and serves anything that could run code as plain text. */
export function Preview({ file, onClose }: { file: FileEntry; onClose: () => void }) {
  const kind = previewKind(file.name);
  const url = api.previewUrl(file.file_uuid);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (kind !== "text") return;
    let live = true;
    fetch(url)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`${r.status} ${r.statusText}`))))
      .then((t) => live && setText(t))
      .catch((e) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [kind, url]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="preview-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <div className="modal-title">
            <h2 id="preview-title">{file.name}</h2>
            <span className="muted small">
              v{file.version} · {formatBytes(file.size)} · verified by SHA-256 before display
            </span>
          </div>
          <a className="btn btn-quiet" href={api.downloadUrl(file.file_uuid)}>
            Download
          </a>
          <button ref={closeRef} type="button" className="btn btn-quiet" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="modal-body">
          {kind === "image" && <img className="preview-media" src={url} alt={file.name} />}
          {kind === "pdf" && <iframe className="preview-frame" src={url} title={file.name} />}
          {kind === "video" && <video className="preview-media" src={url} controls />}
          {kind === "audio" && <audio src={url} controls />}
          {kind === "text" &&
            (error ? (
              <p className="error">Couldn't load the preview: {error}</p>
            ) : text === null ? (
              <p className="muted">Fetching chunks, checking hashes, decrypting…</p>
            ) : (
              <>
                <pre className="preview-text">{text.slice(0, TEXT_LIMIT)}</pre>
                {text.length > TEXT_LIMIT && (
                  <p className="muted small">Showing the first {TEXT_LIMIT.toLocaleString()} characters. Download for the rest.</p>
                )}
              </>
            ))}
          {kind === "none" && <p className="muted">No preview for this file type. Use Download to open it.</p>}
        </div>
      </div>
    </div>
  );
}
