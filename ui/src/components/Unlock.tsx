import { useState, type FormEvent } from "react";
import { api } from "../api";

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
      onDone(`Unlocked as ${r.username}. Restored ${r.files_restored} file${r.files_restored === 1 ? "" : "s"} from peers.`);
      setPassphrase("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card unlock">
      <h2>Unlock this node</h2>
      <p className="muted">
        Keys come from your username and passphrase. On a fresh laptop the same pair recovers every file from the peers.
      </p>
      <form onSubmit={submit} className="unlock-form">
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </label>
        <label>
          Passphrase <span className="muted">(12+ characters)</span>
          <input
            type="password"
            value={passphrase}
            onChange={(e) => setPassphrase(e.target.value)}
            autoComplete="current-password"
            minLength={12}
            required
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Deriving keys…" : "Unlock and recover"}
        </button>
        {error && <p className="error">{error}</p>}
      </form>
    </section>
  );
}
