'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Eye, FileText, Library } from 'lucide-react';
import { ConnectGate, useAuth } from '@/components/AuthProvider';
import { Notice } from '@/components/ui/Notice';
import { PdfPreview } from '@/components/reports/PdfPreview';
import { usePolled } from '@/hooks/usePolled';
import { createReport, fetchMetricsCatalog, fetchOverview, getReport, previewReport } from '@/lib/api';
import type { CatalogItem, FilterOptions, Report, ReportRequest, ReportTemplate } from '@/lib/types';

const TEMPLATES: { id: ReportTemplate; name: string; desc: string }[] = [
  { id: 'executive', name: 'Executive', desc: 'Short summary for decision makers: headline quality, key risks and recommendations.' },
  { id: 'technical', name: 'Technical', desc: 'Per-metric and per-model detail with charts, failure analysis and evidence references.' },
  { id: 'statistical', name: 'Statistical', desc: 'Confidence intervals, significance tests, sample sizes and methodology notes.' },
];
const CHART_OPTIONS: { id: string; label: string }[] = [
  { id: 'model_ranking', label: 'Model ranking' },
  { id: 'llm_performance', label: 'LLM performance' },
  { id: 'rag_quality', label: 'RAG quality' },
  { id: 'agent_outcomes', label: 'Agent outcomes' },
  { id: 'failure_classification', label: 'Failure classification' },
  { id: 'latency_percentiles', label: 'Latency percentiles' },
  { id: 'distributions', label: 'Score distributions' },
  { id: 'confidence_intervals', label: 'Confidence intervals' },
  { id: 'regression', label: 'Regression comparison' },
  { id: 'usage', label: 'Token usage & cost' },
];

function toggle(list: string[], v: string): string[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

function Builder() {
  const { token } = useAuth();
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [catalog, setCatalog] = useState<CatalogItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [title, setTitle] = useState('');
  const [template, setTemplate] = useState<ReportTemplate>('executive');
  const [projectId, setProjectId] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [runs, setRuns] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<string[]>([]);
  const [charts, setCharts] = useState<string[]>([]);
  const [includeCases, setIncludeCases] = useState(false);

  const [busy, setBusy] = useState<'preview' | 'create' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [preview, setPreview] = useState<unknown>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let live = true;
    Promise.all([fetchOverview({}), fetchMetricsCatalog()])
      .then(([ov, cat]) => {
        if (!live) return;
        setOptions(ov.options);
        setCatalog(cat.metrics.filter((m) => m.kind === 'observation'));
        setProjectId((p) => p || ov.options.projects[0]?.id || '');
      })
      .catch((e: unknown) => live && setLoadError(e instanceof Error ? e.message : 'Failed to load options'));
    return () => {
      live = false;
    };
  }, [token]);

  const body = useMemo<ReportRequest>(
    () => ({
      title: title.trim(),
      template,
      project_id: projectId,
      run_ids: runs.length ? runs : undefined,
      model_ids: models.length ? models : undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      metrics: metrics.length ? metrics : undefined,
      charts: charts.length ? charts : undefined,
      include_cases: includeCases,
    }),
    [title, template, projectId, runs, models, dateFrom, dateTo, metrics, charts, includeCases],
  );

  const valid = body.title.length > 0 && !!body.project_id;

  const act = async (kind: 'preview' | 'create') => {
    setBusy(kind);
    setActionError(null);
    try {
      if (kind === 'preview') {
        setPreview((await previewReport(body)).payload);
      } else {
        const r = await createReport(body);
        setJobId(r.id);
      }
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Request failed');
    } finally {
      setBusy(null);
    }
  };

  const loader = useCallback(() => getReport(jobId as string), [jobId]);
  const { data: job, error: pollError } = usePolled<Report>(jobId ? loader : null, (r) => r.status === 'COMPLETED' || r.status === 'FAILED', 2000);
  const current = job && job.id === jobId ? job : null;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Report Builder</h1>
          <p className="text-sm text-slate-600">Create an immutable evidence snapshot and render it to a PDF.</p>
        </div>
        <Link href="/reports/library" className="btn-secondary"><Library size={16} aria-hidden="true" /> Report Library</Link>
      </header>
      {loadError && <Notice tone="error">Could not load options: {loadError}</Notice>}
      {options && options.projects.length === 0 && <Notice tone="warning">No projects exist yet. Create a project and ingest evaluation data first.</Notice>}

      <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); if (valid) void act('create'); }}>
        <fieldset className="card">
          <legend className="label px-1">Template</legend>
          <div className="grid gap-3 md:grid-cols-3">
            {TEMPLATES.map((t) => (
              <label key={t.id} className={`cursor-pointer rounded-md border p-3 ${template === t.id ? 'border-teal-600 bg-teal-50' : 'border-slate-300'}`}>
                <input type="radio" name="template" className="mr-2 accent-teal-700" checked={template === t.id} onChange={() => setTemplate(t.id)} />
                <span className="font-semibold">{t.name}</span>
                <span className="mt-1 block text-xs text-slate-700">{t.desc}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="card grid gap-4 md:grid-cols-2">
          <div className="md:col-span-2">
            <label className="label" htmlFor="r-title">Title</label>
            <input id="r-title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Q3 model quality review" maxLength={200} required />
          </div>
          <div>
            <label className="label" htmlFor="r-project">Project</label>
            <select id="r-project" className="input" value={projectId} onChange={(e) => setProjectId(e.target.value)} required>
              <option value="">Select a project…</option>
              {options?.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="label" htmlFor="r-from">From</label><input id="r-from" type="date" className="input" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /></div>
            <div><label className="label" htmlFor="r-to">To</label><input id="r-to" type="date" className="input" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></div>
          </div>
          <fieldset>
            <legend className="label">Models (none = all)</legend>
            <div className="max-h-40 space-y-1 overflow-y-auto rounded border border-slate-200 p-2">
              {options?.model_ids.length ? options.model_ids.map((m) => (
                <label key={m} className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-teal-700" checked={models.includes(m)} onChange={() => setModels(toggle(models, m))} /> {m}</label>
              )) : <p className="text-sm text-slate-600">No models recorded.</p>}
            </div>
          </fieldset>
          <fieldset>
            <legend className="label">Runs (none = all)</legend>
            <div className="max-h-40 space-y-1 overflow-y-auto rounded border border-slate-200 p-2">
              {options?.runs.length ? options.runs.map((r) => (
                <label key={r.id} className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-teal-700" checked={runs.includes(r.id)} onChange={() => setRuns(toggle(runs, r.id))} /> {r.model_id ?? 'run'} · {r.suite ?? '—'} · {new Date(r.created_at).toLocaleDateString()} <span className="text-xs text-slate-600">({r.status})</span></label>
              )) : <p className="text-sm text-slate-600">No runs recorded.</p>}
            </div>
          </fieldset>
          <fieldset>
            <legend className="label">Quality metrics (none = all available)</legend>
            <div className="max-h-48 space-y-1 overflow-y-auto rounded border border-slate-200 p-2">
              {catalog?.map((m) => {
                const na = m.current.value === null;
                return (
                  <label key={m.key} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" className="accent-teal-700" checked={metrics.includes(m.key)} onChange={() => setMetrics(toggle(metrics, m.key))} /> {m.name}
                    {na && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-semibold text-amber-900" title={m.current.na_reason ?? undefined}>N/A</span>}
                  </label>
                );
              }) ?? <p className="text-sm text-slate-600">Loading…</p>}
            </div>
            <p className="mt-1 text-xs text-slate-600">N/A metrics lack data; selecting them reports N/A with the reason rather than a number.</p>
          </fieldset>
          <fieldset>
            <legend className="label">Charts (none = template default)</legend>
            <div className="max-h-48 space-y-1 overflow-y-auto rounded border border-slate-200 p-2">
              {CHART_OPTIONS.map((c) => (
                <label key={c.id} className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-teal-700" checked={charts.includes(c.id)} onChange={() => setCharts(toggle(charts, c.id))} /> {c.label}</label>
              ))}
            </div>
          </fieldset>
          <label className="flex items-center gap-2 text-sm md:col-span-2"><input type="checkbox" className="h-4 w-4 accent-teal-700" checked={includeCases} onChange={(e) => setIncludeCases(e.target.checked)} /> Include failed test cases</label>
        </div>

        {actionError && <Notice tone="error">{actionError}</Notice>}
        <div className="flex flex-wrap gap-3">
          <button type="button" className="btn-secondary" disabled={!valid || busy !== null} onClick={() => act('preview')}>
            <Eye size={16} aria-hidden="true" /> {busy === 'preview' ? 'Loading preview…' : 'Preview data'}
          </button>
          <button type="submit" className="btn-primary" disabled={!valid || busy !== null}>
            <FileText size={16} aria-hidden="true" /> {busy === 'create' ? 'Submitting…' : 'Generate report'}
          </button>
          {!valid && <span className="self-center text-xs text-slate-600">A title and a project are required.</span>}
        </div>
      </form>

      {preview !== null && (
        <section className="card" aria-label="Report data preview">
          <h2 className="font-semibold">Data preview</h2>
          <p className="mb-2 text-xs text-slate-600">What the snapshot would contain right now (metrics with values or N/A, runs, models, limitations).</p>
          <pre className="max-h-96 overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">{JSON.stringify(preview, null, 2)}</pre>
        </section>
      )}

      {jobId && (
        <section className="card space-y-3" aria-label="Report job">
          <h2 className="font-semibold">Report job</h2>
          {pollError && !current && <Notice tone="error">{pollError}</Notice>}
          {!current && !pollError && <p className="text-sm text-slate-600">Waiting for status…</p>}
          {current && (
            <>
              <p className="text-sm" role="status">
                Status: <span className={`rounded px-2 py-0.5 text-xs font-semibold ${current.status === 'COMPLETED' ? 'bg-teal-100 text-teal-900' : current.status === 'FAILED' ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-900'}`}>{current.status}</span>
                {(current.status === 'PENDING' || current.status === 'GENERATING') && <span className="ml-2 text-xs text-slate-600">checking every 2 seconds…</span>}
              </p>
              {current.status === 'FAILED' && <Notice tone="error">{current.error_message ?? 'Report generation failed.'}</Notice>}
              {current.status === 'COMPLETED' && <PdfPreview reportId={current.id} title={current.title} />}
            </>
          )}
        </section>
      )}
    </div>
  );
}

export default function ReportsPage() {
  return (
    <ConnectGate>
      <Builder />
    </ConnectGate>
  );
}
