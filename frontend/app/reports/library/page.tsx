'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Download, FileJson, RefreshCw, Video } from 'lucide-react';
import { ConnectGate, useAuth } from '@/components/AuthProvider';
import { Modal } from '@/components/ui/Modal';
import { Notice } from '@/components/ui/Notice';
import { getReportSnapshot, listReports, regenerateReport, reportPdfUrl } from '@/lib/api';
import { slug, triggerDownload } from '@/lib/download';
import { formatBytes, formatDateTime } from '@/lib/format';
import type { Report, ReportSnapshot } from '@/lib/types';

function Library() {
  const { token } = useAuth();
  const [reports, setReports] = useState<Report[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<{ report: Report; data: ReportSnapshot } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const load = useCallback(async () => {
    try {
      const r = await listReports();
      setReports(r);
      setError(null);
      return r;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load reports');
      return null;
    }
  }, []);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    const loop = async () => {
      const r = await load();
      if (cancelled) return;
      const pending = r?.some((x) => x.status === 'PENDING' || x.status === 'GENERATING');
      if (pending) timer.current = setTimeout(loop, 2000);
    };
    void loop();
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [token, load, reports === null ? 0 : reports.filter((x) => x.status === 'PENDING' || x.status === 'GENERATING').length]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (id: string, fn: () => Promise<void>) => {
    setRowBusy(id);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Action failed');
    } finally {
      setRowBusy(null);
    }
  };

  const download = (r: Report) =>
    run(r.id, async () => {
      const { url } = await reportPdfUrl(r.id);
      triggerDownload(url, `${slug(r.title)}.pdf`);
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    });
  const regenerate = (r: Report) =>
    run(r.id, async () => {
      await regenerateReport(r.id);
      await load();
    });
  const showSnapshot = (r: Report) =>
    run(r.id, async () => {
      setSnapshot({ report: r, data: await getReportSnapshot(r.id) });
    });

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Report Library</h1>
          <p className="text-sm text-slate-600">Generated reports, their evidence snapshots and PDFs.</p>
        </div>
        <Link href="/reports" className="btn-primary">New report</Link>
      </header>
      {error && <Notice tone="error">{error}</Notice>}
      {reports === null && !error && <p className="text-sm text-slate-600">Loading…</p>}
      {reports && reports.length === 0 && <p className="card text-sm text-slate-700">No reports yet. Use the Report Builder to create one.</p>}
      {reports && reports.length > 0 && (
        <div className="card overflow-x-auto p-0">
          <table className="min-w-full divide-y divide-slate-200">
            <caption className="sr-only">Reports</caption>
            <thead>
              <tr>{['Title', 'Project', 'Created', 'Template', 'Status', 'Size', 'Actions'].map((h) => <th key={h} scope="col" className="th">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {reports.map((r) => {
                const ready = r.status === 'COMPLETED' && !!r.artifact;
                const busy = rowBusy === r.id;
                return (
                  <tr key={r.id}>
                    <th scope="row" className="td text-left font-medium">{r.title}</th>
                    <td className="td font-mono text-xs">{r.project_id.slice(0, 8)}</td>
                    <td className="td">{formatDateTime(r.created_at)}</td>
                    <td className="td capitalize">{r.template}</td>
                    <td className="td">
                      <span className={`rounded px-2 py-0.5 text-xs font-semibold ${r.status === 'COMPLETED' ? 'bg-teal-100 text-teal-900' : r.status === 'FAILED' ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-900'}`}>{r.status}</span>
                      {r.status === 'FAILED' && r.error_message && <p className="mt-1 max-w-xs text-xs text-red-700">{r.error_message}</p>}
                    </td>
                    <td className="td">{r.artifact ? formatBytes(r.artifact.size_bytes) : '—'}</td>
                    <td className="td">
                      <div className="flex flex-wrap gap-2">
                        <button type="button" className="btn-secondary !px-2 !py-1" disabled={!ready || busy} onClick={() => download(r)} title={ready ? 'Download PDF' : 'PDF not available'}><Download size={14} aria-hidden="true" /> Download</button>
                        <button type="button" className="btn-secondary !px-2 !py-1" disabled={busy || r.status === 'PENDING' || r.status === 'GENERATING'} onClick={() => regenerate(r)}><RefreshCw size={14} aria-hidden="true" /> Regenerate</button>
                        <button type="button" className="btn-secondary !px-2 !py-1" disabled={!r.snapshot_id || busy} onClick={() => showSnapshot(r)} title={r.snapshot_id ? undefined : 'No snapshot yet'}><FileJson size={14} aria-hidden="true" /> Snapshot</button>
                        {r.status === 'COMPLETED' ? (
                          <Link href={`/videos?report_id=${encodeURIComponent(r.id)}`} className="btn-secondary !px-2 !py-1"><Video size={14} aria-hidden="true" /> Generate video</Link>
                        ) : (
                          <button type="button" className="btn-secondary !px-2 !py-1" disabled title="Only completed reports can be turned into a video"><Video size={14} aria-hidden="true" /> Generate video</button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <Modal open={!!snapshot} onClose={() => setSnapshot(null)} title={snapshot ? `Snapshot · ${snapshot.report.title}` : 'Snapshot'} wide>
        {snapshot && (
          <div className="space-y-2">
            <p className="text-xs text-slate-700">Schema {String(snapshot.data.schema_version)} · created {formatDateTime(snapshot.data.created_at)} · SHA-256 <span className="break-all font-mono">{snapshot.data.payload_sha256}</span></p>
            <pre className="max-h-[60vh] overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">{JSON.stringify(snapshot.data.payload, null, 2)}</pre>
          </div>
        )}
      </Modal>
    </div>
  );
}

export default function LibraryPage() {
  return (
    <ConnectGate>
      <Library />
    </ConnectGate>
  );
}
