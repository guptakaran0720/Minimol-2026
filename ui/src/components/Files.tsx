import { api, formatBytes, type FileEntry } from "../api";

export function Files({
  files,
  unlocked,
  selected,
  onSelect,
}: {
  files: FileEntry[];
  unlocked: boolean;
  selected: string | null;
  onSelect: (uuid: string) => void;
}) {
  const chunks = files.reduce((n, f) => n + f.chunks, 0);
  return (
    <section className="tile tile-white tile-list s8" aria-labelledby="files-title">
      <div className="tile-head">
        <h2 id="files-title" className="tile-title">
          Files
        </h2>
        {unlocked && files.length > 0 && (
          <span className="muted small">
            {files.length} file{files.length === 1 ? "" : "s"} · {chunks} chunk{chunks === 1 ? "" : "s"} · pick one to map it
          </span>
        )}
      </div>
      {!unlocked ? (
        <p className="empty">Unlock to see your files.</p>
      ) : files.length === 0 ? (
        <p className="empty">No files yet. Drop one on the blue tile to see where its chunks go.</p>
      ) : (
        <ul className="files">
          {files.map((f) => (
            <li key={f.file_uuid} className={f.file_uuid === selected ? "selected" : ""}>
              <button className="file-row" onClick={() => onSelect(f.file_uuid)} aria-pressed={f.file_uuid === selected}>
                <span className="file-name">{f.name}</span>
                <span className="muted small">
                  v{f.version} · {formatBytes(f.size)} · {f.chunks} chunk{f.chunks === 1 ? "" : "s"}
                </span>
              </button>
              <span className={`badge badge-${f.status}`}>{f.status}</span>
              <a
                className="icon-btn"
                href={api.downloadUrl(f.file_uuid)}
                title="Download and verify SHA-256"
                aria-label={`Download ${f.name}`}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M12 5v14M6 13l6 6 6-6" />
                </svg>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
