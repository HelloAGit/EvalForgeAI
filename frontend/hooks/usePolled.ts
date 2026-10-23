'use client';

import { useEffect, useState } from 'react';

/** Polls `load` every `intervalMs` until `isDone` returns true. Cleans up timers on unmount / when `load` changes. */
export function usePolled<T>(load: (() => Promise<T>) | null, isDone: (value: T) => boolean, intervalMs = 2000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!load) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const v = await load();
        if (cancelled) return;
        setData(v);
        setError(null);
        if (!isDone(v)) timer = setTimeout(tick, intervalMs);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Request failed');
        timer = setTimeout(tick, intervalMs * 2);
      }
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, intervalMs]);

  return { data, setData, error };
}
