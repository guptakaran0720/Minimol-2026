import { useState, type FormEvent } from "react";
import { api } from "../api";

/** Takes the upload tile's place while the node is locked. */
export function Unlock({ onDone }: { onDone: (msg: string) => void }) {
  const [username, setUsername] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.recover(username.trim(), passphrase);
      const plural = (n: number) => `${n} file${n === 1 ? "" : "s"}`;
      const parts = [`Unlocked as ${r.username}.`];
      if (r.files_restored > 0) parts.push(`Restored ${plural(r.files_restored)} from peers.`);
      if (r.files_unavailable > 0) parts.push(`${plural(r.files_unavailable)} not reachable yet; retrying every 15 s.`);
      if (r.files_restored === 0 && r.files_unavailable === 0)
        parts.push("No files found for this username and passphrase. If you expected some, check both for a typo.");
      parts.push("New files from other laptops appear here within 15 s.");
      onDone(parts.join(" "));
      setPassphrase("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="tile tile-blue tile-unlock s5 r2" aria-labelledby="unlock-title">
      <span className="pill pill-white">Player 1</span>
      <div className="unlock-body">
        <h2 id="unlock-title" className="drop-title">
          <span className="arc-blink">
            Press
            <br />
            start
          </span>
        </h2>
        <p className="drop-hint">
          Keys come from your username and passphrase. On a fresh laptop the same pair recovers every file from the peers.
        </p>
        <form onSubmit={submit} className="unlock-form">
          <label>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
          </label>
          <label>
            Passphrase <span className="label-hint">12+ characters</span>
            <input
              type="password"
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
              autoComplete="current-password"
              minLength={12}
              required
            />
          </label>
          <button type="submit" className="btn btn-white" disabled={busy}>
            {busy ? "Deriving keys…" : "Unlock and recover"}
          </button>
        </form>
        {error && (
          <p className="tile-note tile-note-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}
