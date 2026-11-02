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
import { RecoveryTile } from "./components/Tiles";
import { Scoreboard } from "./components/Scoreboard";
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
      <header className="arc-top">
        <div className="arc-brand">
          <span className="arc-logo" aria-hidden="true">
            <span className="tone-blue" />
            <span className="tone-red" />
            <span className="tone-yellow" />
            <span className="tone-green" />
          </span>
          <span className="arc-word">
            <span className="visually-hidden">Chunky</span>
            {"CHUNKY".split("").map((c, i) => (
              <span key={i} className={`arc-l arc-l${i}`} aria-hidden="true">
                {c}
              </span>
            ))}
          </span>
        </div>
        {s && (
          <dl className="arc-score">
            <div>
              <dt>1UP</dt>
              <dd>{unlocked ? s.username : "LOCKED"}</dd>
            </div>
            <div>
              <dt>STAGE</dt>
              <dd>{s.node_id ?? "—"}</dd>
            </div>
            <div>
              <dt>PLAYERS</dt>
              <dd>
                {peers.filter((p) => p.state === "alive").length}/{peers.length}
              </dd>
            </div>
          </dl>
        )}
        <div className="arc-actions">
          {s && fakeCodec && <span className="tag tag-warn">DEV codec: not encrypted</span>}
          {s && unlocked && (
            <button type="button" className="btn arc-btn-red" onClick={logout} disabled={busy}>
              Log out
            </button>
          )}
        </div>
      </header>

      {s && <Ticker status={status} items={feed} />}

      <div className="hero arc-hero">
        <h1>
          Every file
          <br />
          gets 3 lives.
        </h1>
        <p>
          Chunks are compressed and encrypted on this laptop, then stacked on 3 different laptops. Lose one and the others
          respawn its chunks.
        </p>
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
          {unlocked && (
            <ChunkMapView map={map.data} file={(files.data ?? []).find((f) => f.file_uuid === selected)} peers={peers} looks={looks} />
          )}
          <Scoreboard stats={s} peers={peers} unlocked={unlocked} map={unlocked ? map.data : null} wide={!unlocked} />
          <Peers
            peers={peers}
            looks={looks}
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
          <Files
            files={files.data ?? []}
            unlocked={unlocked}
            selected={selected}
            onSelect={setSelected}
            onLogs={setLogsFor}
            onPreview={setPreviewing}
            onDelete={remove}
          />
          <Timeline data={timeline.data} />
          <Repair repair={s.repair} scrub={timeline.data?.scrub ?? null} />
          <RecoveryTile username={unlocked ? s.username : null} codec={s.codec} />
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
