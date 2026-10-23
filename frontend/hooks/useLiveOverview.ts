'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE, fetchOverview } from '@/lib/api';
import { authHeader, clearToken, getToken } from '@/lib/auth';
import { LiveConnection, LiveState } from '@/lib/liveConnection';
import type { Filters, Overview } from '@/lib/types';

const INITIAL: LiveState = { status: 'connecting', stale: false, lastUpdated: null, lastEventId: 0, error: null };

export function useLiveOverview(filters: Filters, enabled: boolean, startPaused: boolean) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [live, setLive] = useState<LiveState>(INITIAL);
  const [paused, setPaused] = useState(startPaused);
  const connRef = useRef<LiveConnection<Overview> | null>(null);
  const pausedRef = useRef(startPaused);
  const key = JSON.stringify(filters);

  useEffect(() => {
    pausedRef.current = startPaused;
    setPaused(startPaused);
  }, [startPaused]);

  useEffect(() => {
    if (!enabled) return;
    const f = JSON.parse(key) as Filters;
    setLive(INITIAL);
    const conn = new LiveConnection<Overview>({
      baseUrl: API_BASE,
      fetchImpl: (input, init) => fetch(input, init),
      getHeaders: () => authHeader(getToken()),
      loadOverview: (signal) => fetchOverview(f, signal),
      onOverview: setOverview,
      onState: setLive,
      onUnauthorized: clearToken,
    });
    connRef.current = conn;
    if (pausedRef.current) conn.pause();
    conn.start();
    return () => {
      conn.dispose();
      connRef.current = null;
    };
  }, [enabled, key]);

  const pause = useCallback(() => {
    pausedRef.current = true;
    setPaused(true);
    connRef.current?.pause();
  }, []);
  const resume = useCallback(() => {
    pausedRef.current = false;
    setPaused(false);
    connRef.current?.resume();
  }, []);

  return { overview, live, paused, pause, resume };
}
