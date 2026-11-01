import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Calls `load` now and every `ms` while `key` is not null; restarts when `key` changes.
 * Keeps the last good value when a call fails and reports the error separately.
 */
export function usePoll<T>(load: () => Promise<T>, ms: number, key: string | null = "") {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;

  const refresh = useCallback(async () => {
    try {
      setData(await loadRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    setData(null);
    if (key === null) return;
    refresh();
    const id = window.setInterval(refresh, ms);
    return () => window.clearInterval(id);
  }, [key, ms, refresh]);

  return { data, error, refresh };
}
