import { api, formatBytes, type FileEntry } from "../api";

export function Files({
  files,
  selected,
  onSelect,
}: {
  files: FileEntry[];
  selected: string | null;
  onSelect: (uuid: string) => void;
}) {
  return (
    <section className="card">
      <header className="card-head">
        <h2>Files</h2>
        <span className="muted">{files.length} stored</span>
      </header>
      {files.length === 0 ? (
        <p className="empty">No files yet. Upload one to see where its chunks go.</p>
      ) : (
        <ul className="files">
          {files.map((f) => (
            <li key={f.file_uuid} className={f.file_uuid === selected ? "selected" : ""}>
              <button className="file-row" onClick={() => onSelect(f.file_uuid)}>
                <span className="file-name">{f.name}</span>
                <span className="muted">
                  v{f.version} · {formatBytes(f.size)} · {f.chunks} chunk{f.chunks === 1 ? "" : "s"}
                </span>
                <span className={`badge badge-${f.status}`}>{f.status}</span>
              </button>
              <a className="download" href={api.downloadUrl(f.file_uuid)} title="Download and verify SHA-256">
                Download
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
