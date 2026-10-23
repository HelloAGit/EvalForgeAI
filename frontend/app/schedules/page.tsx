'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { ConnectGate, useAuth } from '@/components/AuthProvider';
import { Notice } from '@/components/ui/Notice';
import { ApiError, listSchedules, setScheduleEnabled } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import type { Schedule } from '@/lib/types';

function Schedules() {
  const { token } = useAuth();
  const [items, setItems] = useState<Schedule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await listSchedules());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load schedules');
    }
  }, []);
  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  const toggle = async (s: Schedule) => {
    setBusy(s.id);
    setError(null);
    try {
      const updated = await setScheduleEnabled(s.id, !s.enabled);
      setItems((cur) => cur?.map((x) => (x.id === s.id ? updated : x)) ?? null);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 403 ? 'Changing schedules requires an admin token (403 Forbidden).' : e instanceof Error ? e.message : 'Update failed');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-bold">Scheduled evaluations</h1>
        <p className="text-sm text-slate-600">Enable or disable recurring evaluation jobs. Changing a schedule requires an admin token.</p>
      </header>
      {error && <Notice tone="error">{error}</Notice>}
      {items === null && !error && <p className="text-sm text-slate-600">Loading…</p>}
      {items && items.length === 0 && <p className="card text-sm text-slate-700">No schedules are configured. Create one with POST /api/v1/schedules (admin).</p>}
      {items && items.length > 0 && (
        <div className="card overflow-x-auto p-0">
          <table className="min-w-full divide-y divide-slate-200">
            <caption className="sr-only">Schedules</caption>
            <thead>
              <tr>{['Name', 'Kind', 'State', 'Next run', 'Last run', 'Last status', 'Action'].map((h) => <th key={h} scope="col" className="th">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((s) => (
                <tr key={s.id}>
                  <th scope="row" className="td text-left font-medium">{s.name}</th>
                  <td className="td">{s.kind}</td>
                  <td className="td">
                    <span className={`rounded px-2 py-0.5 text-xs font-semibold ${s.enabled ? 'bg-teal-100 text-teal-900' : 'bg-slate-200 text-slate-800'}`}>{s.enabled ? 'Enabled' : 'Disabled'}</span>
                  </td>
                  <td className="td">{formatDateTime(s.next_run_at)}</td>
                  <td className="td">{formatDateTime(s.last_run_at)}</td>
                  <td className="td text-xs">{s.last_status ?? '—'}{s.last_skip_reason ? ` (skipped: ${s.last_skip_reason})` : ''}</td>
                  <td className="td">
                    <button type="button" className={s.enabled ? 'btn-secondary' : 'btn-primary'} disabled={busy === s.id} onClick={() => toggle(s)}>
                      {busy === s.id ? 'Working…' : s.enabled ? 'Disable' : 'Enable'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function SchedulesPage() {
  return (
    <ConnectGate>
      <Schedules />
    </ConnectGate>
  );
}
