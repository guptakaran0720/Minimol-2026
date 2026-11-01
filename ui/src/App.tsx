import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type FileEntry, type UploadResult } from "./api";
import { usePoll } from "./usePoll";
import { useClusterFeed } from "./feed";
import { peerLooks } from "./identity";
import { ChunkMapView } from "./components/ChunkMapView";
import { FileLogs } from "./components/FileLogs";
import { Files } from "./components/Files";
import { Peers } from "./components/Peers";
import { Preview } from "./components/Preview";
import { Repair } from "./components/Repair";
import { Timeline } from "./components/Timeline";
import { Ticker, type TickerLine } from "./components/Ticker";
import { HealthTile, LinkTile, PeersTile, RecoveryTile, RepairTile } from "./components/Tiles";
import { Unlock } from "./components/Unlock";
import { Upload } from "./components/Upload";

const POLL_MS = 2000;

export default function App() {
  const stats = usePoll(api.stats, POLL_MS);
  const timeline = usePoll(api.events, POLL_MS);
  const drain = usePoll(api.drain, POLL_MS);
  const [logsFor, setLogsFor] = useState<string | null>(null);
  const unlocked = stats.data?.unlocked ?? false;
  const files = usePoll(api.files, POLL_MS, unlocked ? "files" : null);
  const [selected, setSelected] = useState<string | null>(null);
  const loadMap = useCallback(() => api.map(selected ?? ""), [selected]);
  const map = usePoll(loadMap, POLL_MS, unlocked ? selected : null);
  const [notice, setNotice] = useState<string | null>(null);
  const [lastUpload, setLastUpload] = useState<UploadResult | null>(null);
  const [previewing, setPreviewing] = useState<FileEntry | null>(null);
  const [busy, setBusy] = useState(false);

  async function logout() {
    setBusy(true);
    try {
      await api.logout();
      setSelected(null);
      setLastUpload(null);
      setPreviewing(null);
      setNotice("Logged out. Your keys are gone from this laptop; your files stay safe on the peers. Unlock again to see them.");
    } catch (e) {
      setNotice(`Log out failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
      stats.refresh();
    }
  }

  async function remove(f: FileEntry) {
    if (!window.confirm(`Delete "${f.name}" from every laptop? Its chunks are erased from the peers and this can't be undone.`)) return;
    try {
      const r = await api.deleteFile(f.file_uuid);
      setNotice(
        `Deleted ${r.name}: ${r.copies_deleted} stored cop${r.copies_deleted === 1 ? "y" : "ies"} erased from the peers.` +
          (r.pending_objects ? ` ${r.pending_objects} piece${r.pending_objects === 1 ? "" : "s"} sit on an offline laptop and will be erased when it returns.` : ""),
      );
      if (selected === f.file_uuid) setSelected(null);
    } catch (e) {
      setNotice(`Delete failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      files.refresh();
      stats.refresh();
    }
  }

  // Keep a file selected so the chunk map is always showing something useful.
  useEffect(() => {
    const list = files.data ?? [];
    if (list.length && !list.some((f) => f.file_uuid === selected)) setSelected(list[list.length - 1].file_uuid);
  }, [files.data, selected]);

  const s = stats.data;
  const peers = s?.peers ?? [];
  const looks = useMemo(() => peerLooks(peers), [peers]);
  const feed = useClusterFeed(timeline.data, s, unlocked ? files.data : null, lastUpload);
  const fakeCodec = s?.codec.startsWith("FAKE");

  const status: TickerLine[] = [];
  if (s) {
    const alive = peers.filter((p) => p.state === "alive").length;
    status.push({ text: `${alive} of ${peers.length} laptop${peers.length === 1 ? "" : "s"} alive`, tone: alive === peers.length ? "green" : "yellow" });
    for (const p of peers) {
      if (p.state === "dead") status.push({ text: `${p.node_id} is down`, tone: "red" });
      else if (p.state === "suspect") status.push({ text: `${p.node_id} is not answering`, tone: "yellow" });
      else if (p.state === "draining") status.push({ text: `${p.node_id} is draining · its chunks are moving to the others`, tone: "blue" });
      else if (p.tier === 2) status.push({ text: `${p.node_id} in the slow tier · ${p.rtt_ms.toFixed(0)} ms`, tone: "yellow" });
    }
    if (unlocked) {
      const f = s.files;
      status.push({
        text: `${f.healthy} of ${f.count} file${f.count === 1 ? "" : "s"} healthy`,
        tone: f.unavailable ? "red" : f.degraded ? "yellow" : "green",
      });
    } else {
      status.push({ text: "locked · unlock to see your files", tone: "blue" });
    }
    if (feed.length === 0) status.push({ text: `self-repair checks every 10 s · ${s.repair.total_copies} copies re-made so far`, tone: "blue" });
  }

  return (
    <div className="page">
      <header className="top">
        <div className="brand">
          <span className="wordmark">
            chunky<span className="wordmark-dot">.</span>
          </span>
          {s?.node_id && (
            <span className="mono muted" title="The laptop serving this dashboard">
              node {s.node_id}
            </span>
          )}
        </div>
        <div className="top-meta">
          {s && fakeCodec && <span className="tag tag-warn">DEV codec: not encrypted</span>}
          {s && (
            <span className={`status-pill ${unlocked ? "is-ok" : ""}`}>
              <span className="status-dot" aria-hidden="true" />
              {unlocked ? `unlocked · ${s.username}` : "locked"}
            </span>
          )}
          {s && unlocked && (
            <button type="button" className="btn btn-quiet" onClick={logout} disabled={busy}>
              Log out
            </button>
          )}
        </div>
      </header>

      <div className="hero">
        <h1>
          Live from the <span className="accent">cluster.</span>
        </h1>
        <p className="muted">Peer-to-peer storage · compressed and encrypted on this laptop · self-healing</p>
      </div>

      {(stats.error || notice) && (
        <div className="banners">
          {stats.error && (
            <div className="banner banner-error" role="alert">
              Can't reach this node's API ({stats.error}). Showing the last data received.
            </div>
          )}
          {notice && (
            <div className="banner banner-ok" role="status">
              <span>{notice}</span>
              <button type="button" className="btn btn-quiet" onClick={() => setNotice(null)}>
                Dismiss
              </button>
            </div>
          )}
        </div>
      )}

      {s && <Ticker status={status} items={feed} />}

      {s ? (
        <main className="bento">
          {unlocked ? (
            <Upload
              onUploaded={(r) => {
                setLastUpload(r);
                setSelected(r.file_uuid);
                files.refresh();
                stats.refresh();
              }}
            />
          ) : (
            <Unlock
              onDone={(msg) => {
                setNotice(msg);
                stats.refresh();
              }}
            />
          )}
          <PeersTile peers={peers} looks={looks} />
          <HealthTile stats={s} unlocked={unlocked} />
          <LinkTile peers={peers} looks={looks} />
          <RepairTile repair={s.repair} />
          <Files
            files={files.data ?? []}
            unlocked={unlocked}
            selected={selected}
            onSelect={setSelected}
            onLogs={setLogsFor}
            onPreview={setPreviewing}
            onDelete={remove}
          />
          <RecoveryTile username={unlocked ? s.username : null} codec={s.codec} />
          {unlocked && (
            <ChunkMapView map={map.data} file={(files.data ?? []).find((f) => f.file_uuid === selected)} peers={peers} looks={looks} />
          )}
          <Timeline data={timeline.data} wide={!unlocked} />
          <Repair repair={s.repair} scrub={timeline.data?.scrub ?? null} />
          <Peers
            peers={peers}
            looks={looks}
            wide={!unlocked}
            drain={drain.data}
            onDrain={async (on) => {
              try {
                await api.setDrain(on);
              } finally {
                drain.refresh();
                stats.refresh();
              }
            }}
          />
        </main>
      ) : (
        !stats.error && <p className="loading">Connecting to this node…</p>
      )}
      {previewing && unlocked && <Preview file={previewing} onClose={() => setPreviewing(null)} />}
      {logsFor && (files.data ?? []).some((f) => f.file_uuid === logsFor) && (
        <FileLogs
          file={(files.data ?? []).find((f) => f.file_uuid === logsFor)!}
          peers={peers}
          onClose={() => setLogsFor(null)}
        />
      )}
    </div>
  );
}
