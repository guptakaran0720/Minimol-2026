import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { usePoll } from "./usePoll";
import { ChunkMapView } from "./components/ChunkMapView";
import { Files } from "./components/Files";
import { Peers } from "./components/Peers";
import { Repair } from "./components/Repair";
import { Unlock } from "./components/Unlock";
import { Upload } from "./components/Upload";

const POLL_MS = 2000;

export default function App() {
  const stats = usePoll(api.stats, POLL_MS);
  const unlocked = stats.data?.unlocked ?? false;
  const files = usePoll(api.files, POLL_MS, unlocked ? "files" : null);
  const [selected, setSelected] = useState<string | null>(null);
  const loadMap = useCallback(() => api.map(selected ?? ""), [selected]);
  const map = usePoll(loadMap, POLL_MS, unlocked ? selected : null);
  const [notice, setNotice] = useState<string | null>(null);

  // Keep a file selected so the chunk map is always showing something useful.
  useEffect(() => {
    const list = files.data ?? [];
    if (list.length && !list.some((f) => f.file_uuid === selected)) setSelected(list[list.length - 1].file_uuid);
  }, [files.data, selected]);

  const s = stats.data;
  const fakeCodec = s?.codec.startsWith("FAKE");
  const peers = s?.peers ?? [];

  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>Minimol Storage</h1>
          <p className="muted">Peer-to-peer · client-side compressed and encrypted · self-healing</p>
        </div>
        <div className="top-meta">
          {s?.node_id && (
            <span className="tag mono" title="The node serving this dashboard">
              {s.node_id}
            </span>
          )}
          {s && <span className={`tag ${fakeCodec ? "tag-warn" : ""}`}>{fakeCodec ? "DEV codec: not encrypted" : s.codec}</span>}
          {s && (
            <span className={`tag ${unlocked ? "tag-ok" : ""}`}>{unlocked ? `unlocked · ${s.username}` : "locked"}</span>
          )}
        </div>
      </header>

      {stats.error && (
        <div className="banner error">
          Can't reach this node's API ({stats.error}). Showing the last data received.
        </div>
      )}
      {notice && (
        <div className="banner ok" onClick={() => setNotice(null)}>
          {notice}
        </div>
      )}

      {s && (
        <div className="summary">
          <div>
            <span className="big">{peers.filter((p) => p.state === "alive").length}</span>
            <span className="muted">peers alive</span>
          </div>
          <div>
            <span className="big">{s.files.healthy}</span>
            <span className="muted">files healthy</span>
          </div>
          <div>
            <span className={`big ${s.files.degraded ? "warn" : ""}`}>{s.files.degraded}</span>
            <span className="muted">degraded</span>
          </div>
          <div>
            <span className={`big ${s.files.unavailable ? "bad" : ""}`}>{s.files.unavailable}</span>
            <span className="muted">unavailable</span>
          </div>
          <div>
            <span className="big">{s.repair.total_copies}</span>
            <span className="muted">repair copies by this node</span>
          </div>
        </div>
      )}

      <main className="grid">
        <div className="col">
          {s && !unlocked && <Unlock onDone={(msg) => { setNotice(msg); stats.refresh(); }} />}
          {unlocked && (
            <Upload
              onUploaded={(r) => {
                setSelected(r.file_uuid);
                files.refresh();
              }}
            />
          )}
          {unlocked && <Files files={files.data ?? []} selected={selected} onSelect={setSelected} />}
          <Peers peers={peers} />
        </div>
        <div className="col">
          {unlocked && (
            <ChunkMapView map={map.data} file={(files.data ?? []).find((f) => f.file_uuid === selected)} peers={peers} />
          )}
          {s && <Repair repair={s.repair} />}
        </div>
      </main>
    </div>
  );
}
