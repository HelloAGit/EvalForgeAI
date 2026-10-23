'use client';

import React, { useEffect, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Pause, Play, Settings2 } from 'lucide-react';
import { Modal } from '@/components/ui/Modal';
import { Notice } from '@/components/ui/Notice';
import { ChartCard } from '@/components/ui/ChartCard';
import { fetchAlerts, fetchCompare, fetchMetricDetail, fetchMubitStatus, savePreferences } from '@/lib/api';
import { NA, formatCi, formatClock, formatPValue, formatValue } from '@/lib/format';
import type { Alert, CaseRow, CompareResult, Filters, Kpi, MetricDetail, MubitStatus, Overview, Preferences, QualityIndex } from '@/lib/types';
import type { LiveState } from '@/lib/liveConnection';

// ---------------------------------------------------------------- live status
export function statusPill(live: LiveState, paused: boolean): { label: string; cls: string } {
  if (paused || live.status === 'paused') return { label: 'Paused', cls: 'bg-slate-200 text-slate-800' };
  if (live.status === 'unauthorized') return { label: 'Not connected', cls: 'bg-red-100 text-red-800' };
  if (live.stale) return { label: 'Stale', cls: 'bg-amber-100 text-amber-900' };
  if (live.status === 'live') return { label: 'Live', cls: 'bg-teal-100 text-teal-900' };
  if (live.status === 'polling') return { label: 'Polling', cls: 'bg-blue-100 text-blue-900' };
  if (live.status === 'reconnecting') return { label: 'Reconnecting', cls: 'bg-amber-100 text-amber-900' };
  return { label: 'Connecting', cls: 'bg-slate-100 text-slate-800' };
}

export function LiveHeader({ live, paused, onPause, onResume }: { live: LiveState; paused: boolean; onPause: () => void; onResume: () => void }) {
  const pill = statusPill(live, paused);
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <span role="status" aria-live="polite" className={`rounded-full px-3 py-1 text-xs font-semibold ${pill.cls}`}>
        {pill.label}
      </span>
      <span className="text-xs text-slate-600">Last updated: {formatClock(live.lastUpdated)}</span>
      {live.error && !paused && <span className="max-w-xs truncate text-xs text-amber-800" title={live.error}>{live.error}</span>}
      <button type="button" className="btn-secondary !py-1" onClick={paused ? onResume : onPause}>
        {paused ? <Play size={14} aria-hidden="true" /> : <Pause size={14} aria-hidden="true" />}
        {paused ? 'Resume' : 'Pause'}
      </button>
    </div>
  );
}

export function MubitBanner({ enabled }: { enabled: boolean }) {
  const [st, setSt] = useState<MubitStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled) return;
    fetchMubitStatus().then(setSt).catch((e: unknown) => setErr(e instanceof Error ? e.message : 'unavailable'));
  }, [enabled]);
  let text = 'Checking…';
  let cls = 'bg-slate-300';
  if (err) {
    text = `status unavailable (${err})`;
  } else if (st) {
    cls = st.configured && st.connection_active ? 'bg-teal-600' : 'bg-amber-500';
    text = !st.configured ? 'not configured' : st.connection_active ? `connected · ${st.model}` : `configured, connection inactive${st.message ? ` – ${st.message}` : ''}`;
  }
  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium">
      <span className="text-slate-600">Mubit Router:</span>
      <span className={`h-2 w-2 rounded-full ${cls}`} aria-hidden="true" />
      <span className="text-slate-800">{text}</span>
    </div>
  );
}

// ---------------------------------------------------------------- filters
const FILTER_FIELDS: { key: keyof Filters; label: string }[] = [
  { key: 'project_id', label: 'Project' },
  { key: 'provider', label: 'Provider' },
  { key: 'model_id', label: 'Model' },
  { key: 'suite', label: 'Suite' },
  { key: 'dataset_version', label: 'Dataset version' },
  { key: 'run_id', label: 'Run' },
  { key: 'category', label: 'Category' },
  { key: 'status', label: 'Status' },
];

export function FilterBar({ options, filters, onChange }: { options: Overview['options']; filters: Filters; onChange: (f: Filters) => void }) {
  const list = (k: keyof Filters): { v: string; l: string }[] => {
    switch (k) {
      case 'project_id': return options.projects.map((p) => ({ v: p.id, l: p.name }));
      case 'provider': return options.providers.map((v) => ({ v, l: v }));
      case 'model_id': return options.model_ids.map((v) => ({ v, l: v }));
      case 'suite': return options.suites.map((v) => ({ v, l: v }));
      case 'dataset_version': return options.dataset_versions.map((v) => ({ v, l: v }));
      case 'run_id': return options.runs.map((r) => ({ v: r.id, l: `${r.model_id ?? 'run'} · ${r.suite ?? '—'} · ${new Date(r.created_at).toLocaleDateString()} (${r.id.slice(0, 6)})` }));
      case 'category': return options.categories.map((v) => ({ v, l: v.toUpperCase() }));
      case 'status': return options.statuses.map((v) => ({ v, l: v }));
      default: return [];
    }
  };
  const set = (k: keyof Filters, v: string) => onChange({ ...filters, [k]: v || undefined });
  const active = Object.values(filters).some(Boolean);
  return (
    <form className="card grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5" aria-label="Dashboard filters" onSubmit={(e) => e.preventDefault()}>
      {FILTER_FIELDS.map((f) => {
        const items = list(f.key);
        const cur = filters[f.key] ?? '';
        const known = !cur || items.some((i) => i.v === cur);
        return (
          <div key={f.key}>
            <label className="label" htmlFor={`f-${f.key}`}>{f.label}</label>
            <select id={`f-${f.key}`} className="input" value={cur} onChange={(e) => set(f.key, e.target.value)}>
              <option value="">All</option>
              {!known && <option value={cur}>{cur}</option>}
              {items.map((i) => <option key={i.v} value={i.v}>{i.l}</option>)}
            </select>
          </div>
        );
      })}
      <div>
        <label className="label" htmlFor="f-date_from">From</label>
        <input id="f-date_from" type="date" className="input" value={filters.date_from ?? ''} onChange={(e) => set('date_from', e.target.value)} />
      </div>
      <div>
        <label className="label" htmlFor="f-date_to">To</label>
        <input id="f-date_to" type="date" className="input" value={filters.date_to ?? ''} onChange={(e) => set('date_to', e.target.value)} />
      </div>
      <div className="flex items-end">
        <button type="button" className="btn-secondary w-full" disabled={!active} onClick={() => onChange({})}>Clear filters</button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- quality index
export function QualityIndexCard({ qi, onOpen }: { qi: QualityIndex; onOpen: () => void }) {
  const na = qi.value === null;
  return (
    <section className="card" aria-label="Overall AI Quality Index">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-600">Overall AI Quality Index</h2>
          <p className={`mt-1 text-4xl font-bold ${na ? 'text-amber-700' : 'text-teal-800'}`}>{na ? NA : `${qi.value!.toFixed(1)} / 100`}</p>
          {na && <p className="mt-1 max-w-xl text-sm text-slate-700">{qi.na_reason}</p>}
        </div>
        <div className="w-full max-w-xs">
          <div className="flex justify-between text-xs text-slate-700">
            <span>Metric coverage</span>
            <span>{(qi.coverage * 100).toFixed(0)}% (min {(qi.min_coverage * 100).toFixed(0)}%)</span>
          </div>
          <div className="mt-1 h-2 rounded bg-slate-200" role="progressbar" aria-label="Metric coverage" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(qi.coverage * 100)}>
            <div className={`h-2 rounded ${qi.coverage >= qi.min_coverage ? 'bg-teal-600' : 'bg-amber-500'}`} style={{ width: `${Math.min(100, qi.coverage * 100)}%` }} />
          </div>
          <button type="button" className="mt-2 text-xs font-medium text-teal-800 underline" onClick={onOpen}>Index details</button>
        </div>
      </div>
      <p className="mt-3 text-xs text-slate-600">{qi.method}. Needs at least {qi.min_observations} observations per metric.</p>
      {qi.missing.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer font-medium text-amber-800">{qi.missing.length} metric(s) not contributing — why?</summary>
          <ul className="mt-2 space-y-1">
            {qi.missing.map((m) => (
              <li key={m.key} className="text-xs text-slate-700"><span className="font-semibold">{m.name}</span> (weight {m.weight}): {m.reason}</li>
            ))}
          </ul>
        </details>
      )}
      {qi.components.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer font-medium text-slate-700">{qi.components.length} contributing metric(s)</summary>
          <ul className="mt-2 grid gap-1 sm:grid-cols-2">
            {qi.components.map((c) => (
              <li key={c.key} className="text-xs text-slate-700">{c.name}: mean {(c.mean * 100).toFixed(1)}% · weight {c.weight} · n={c.n}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- configure KPIs
export function ConfigureKpis({ open, onClose, kpis, prefs, onSaved }: { open: boolean; onClose: () => void; kpis: Kpi[]; prefs: Preferences; onSaved: (p: Preferences) => void }) {
  const list = kpis.filter((k) => k.key !== 'quality_index');
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [auto, setAuto] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (open) {
      setSel(new Set(prefs.visible_kpis.length ? prefs.visible_kpis : list.map((k) => k.key)));
      setAuto(prefs.auto_refresh);
      setErr(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const toggle = (k: string) => setSel((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const save = async () => {
    if (sel.size === 0) { setErr('Select at least one KPI.'); return; }
    setSaving(true);
    setErr(null);
    try {
      const saved = await savePreferences({ visible_kpis: list.map((k) => k.key).filter((k) => sel.has(k)), default_filters: prefs.default_filters, auto_refresh: auto });
      onSaved(saved);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not save preferences');
    } finally {
      setSaving(false);
    }
  };
  const cats = Array.from(new Set(list.map((k) => k.category)));
  return (
    <Modal open={open} onClose={onClose} title="Configure KPIs" wide>
      <div className="space-y-4">
        {err && <Notice tone="error">{err}</Notice>}
        {cats.map((c) => (
          <fieldset key={c}>
            <legend className="label">{c}</legend>
            <div className="grid gap-1 sm:grid-cols-2">
              {list.filter((k) => k.category === c).map((k) => (
                <label key={k.key} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={sel.has(k.key)} onChange={() => toggle(k.key)} className="h-4 w-4 accent-teal-700" /> {k.name}
                </label>
              ))}
            </div>
          </fieldset>
        ))}
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} className="h-4 w-4 accent-teal-700" /> Auto-refresh with live updates
        </label>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="button" className="btn-primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </div>
    </Modal>
  );
}

export function ConfigureButton({ onClick }: { onClick: () => void }) {
  return <button type="button" className="btn-secondary" onClick={onClick}><Settings2 size={16} aria-hidden="true" /> Configure KPIs</button>;
}

// ---------------------------------------------------------------- KPI drill-down
function CaseTable({ rows, caption }: { rows: CaseRow[]; caption: string }) {
  if (!rows.length) return <p className="text-sm text-slate-600">None recorded.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200 text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead><tr><th className="th" scope="col">Evidence</th><th className="th" scope="col">Model</th><th className="th" scope="col">Value</th><th className="th" scope="col">Status</th><th className="th" scope="col">Prompt</th></tr></thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={`${r.evidence_ref}-${i}`}>
              <td className="px-3 py-1.5 font-mono">{r.evidence_ref}</td>
              <td className="px-3 py-1.5">{r.model_id ?? '—'}</td>
              <td className="px-3 py-1.5">{r.value === undefined ? '—' : r.value.toFixed(3)}</td>
              <td className="px-3 py-1.5">{r.error_type ?? r.status ?? '—'}</td>
              <td className="px-3 py-1.5 max-w-xs truncate" title={r.prompt_excerpt}>{r.prompt_excerpt ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function KpiDrawer({ metricKey, filters, onClose }: { metricKey: string | null; filters: Filters; onClose: () => void }) {
  const [detail, setDetail] = useState<MetricDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const fkey = JSON.stringify(filters);
  useEffect(() => {
    if (!metricKey) return;
    setDetail(null);
    setErr(null);
    const ac = new AbortController();
    fetchMetricDetail(metricKey, JSON.parse(fkey) as Filters, ac.signal).then(setDetail).catch((e: unknown) => {
      if (!ac.signal.aborted) setErr(e instanceof Error ? e.message : 'Failed to load details');
    });
    return () => ac.abort();
  }, [metricKey, fkey]);

  const unit = detail?.metric.unit ?? 'ratio';
  const trendRows = (() => {
    const m = new Map<string, Record<string, number | string>>();
    for (const s of detail?.trend?.series ?? []) for (const p of s.points) { const r = m.get(p.t) ?? { t: p.t }; r[s.model_id] = unit === 'ratio' ? p.value * 100 : p.value; m.set(p.t, r); }
    return Array.from(m.values()).sort((a, b) => String(a.t).localeCompare(String(b.t)));
  })();
  const trendModels = (detail?.trend?.series ?? []).map((s) => s.model_id);
  const k = detail?.kpi;

  return (
    <Modal open={!!metricKey} onClose={onClose} title={detail?.metric.name ?? 'Metric details'} side>
      {err && <Notice tone="error">{err}</Notice>}
      {!detail && !err && <p className="text-sm text-slate-600">Loading…</p>}
      {detail && k && (
        <div className="space-y-5 text-sm">
          <div>
            <p className={`text-3xl font-bold ${k.value === null ? 'text-amber-700' : 'text-slate-900'}`}>{formatValue(k.value, k.unit)}</p>
            {k.value === null && <p className="mt-1 text-slate-700">{k.na_reason}</p>}
            <p className="mt-1 text-xs text-slate-600">n = {k.n_observations}{k.ci ? ` · 95% CI ${formatCi(k.ci, k.unit)}` : ''} · unit: {detail.metric.unit}</p>
          </div>
          <dl className="space-y-2">
            <div><dt className="label">Definition</dt><dd>{detail.metric.definition}</dd></div>
            <div><dt className="label">Calculation</dt><dd>{detail.metric.calculation}</dd></div>
            <div><dt className="label">Evaluation method</dt><dd>{detail.evaluation_method.method} · version {detail.evaluation_method.version} · {detail.evaluation_method.producer}</dd></div>
            <div><dt className="label">Models</dt><dd>{detail.models.length ? detail.models.join(', ') : '—'}</dd></div>
            <div><dt className="label">Dataset versions</dt><dd>{detail.dataset_versions.length ? detail.dataset_versions.join(', ') : '—'}</dd></div>
          </dl>
          <ChartCard
            title="Trend" description="Daily trend of this metric per model." height={200}
            empty={trendRows.length ? null : detail.trend?.na_reason ?? 'No trend available for this metric.'}
            table={{ headers: ['Day', ...trendModels], rows: trendRows.map((r) => [String(r.t).slice(0, 10), ...trendModels.map((m) => (r[m] === undefined ? NA : Number(r[m]).toFixed(2)))]) }}
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendRows}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="t" tickFormatter={(t: string) => t.slice(5, 10)} tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                {trendModels.map((m, i) => <Line key={m} dataKey={m} stroke={['#0f766e', '#2563eb', '#d97706', '#7c3aed'][i % 4]} connectNulls />)}
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
          {detail.distribution && (
            <ChartCard
              title="Score distribution" description="Histogram of observed scores." height={160}
              empty={detail.distribution.counts.some((c) => c > 0) ? null : 'No observations.'}
              table={{ headers: ['Bin', 'Count'], rows: detail.distribution.counts.map((c, i) => [detail.distribution!.bins[i].toFixed(1), c]) }}
            >
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={detail.distribution.counts.map((c, i) => ({ bin: detail.distribution!.bins[i].toFixed(1), count: c }))}>
                  <XAxis dataKey="bin" tick={{ fontSize: 11 }} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} /><Tooltip />
                  <Bar dataKey="count" name="Observations" fill="#0f766e" />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          )}
          <div><h3 className="label">Failed cases</h3><CaseTable rows={detail.failed_cases} caption="Failed cases" /></div>
          <div><h3 className="label">Related cases</h3><CaseTable rows={detail.related_cases} caption="Related cases" /></div>
          <div>
            <h3 className="label">Evidence references</h3>
            {detail.evidence_refs.length ? <ul className="flex flex-wrap gap-1">{detail.evidence_refs.map((e) => <li key={e} className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs">{e}</li>)}</ul> : <p className="text-slate-600">None.</p>}
          </div>
        </div>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------- alerts
export function AlertsPanel({ filters, refreshKey, enabled }: { filters: Filters; refreshKey: number; enabled: boolean }) {
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const fkey = JSON.stringify(filters);
  useEffect(() => {
    if (!enabled) return;
    const ac = new AbortController();
    fetchAlerts(JSON.parse(fkey) as Filters, ac.signal).then((r) => { setAlerts(r.alerts); setErr(null); }).catch((e: unknown) => { if (!ac.signal.aborted) setErr(e instanceof Error ? e.message : 'Failed to load alerts'); });
    return () => ac.abort();
  }, [fkey, refreshKey, enabled]);
  return (
    <section className="card" aria-label="Regression alerts">
      <h3 className="text-sm font-semibold">Regression alerts</h3>
      <p className="mb-2 text-xs text-slate-600">Metrics where the latest run is worse than the previous comparable run. Critical = statistically significant (Welch t-test).</p>
      {err && <Notice tone="error">{err}</Notice>}
      {alerts === null && !err && <p className="text-sm text-slate-600">Loading…</p>}
      {alerts && alerts.length === 0 && <p className="rounded border border-dashed border-slate-300 bg-slate-50 p-3 text-sm text-slate-700">No regressions detected.</p>}
      <ul className="space-y-2">
        {alerts?.map((a) => (
          <li key={a.id} className={`rounded border-l-4 bg-slate-50 p-3 text-sm ${a.severity === 'critical' ? 'border-red-600' : 'border-amber-500'}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded px-2 py-0.5 text-xs font-semibold ${a.severity === 'critical' ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-900'}`}>{a.severity}</span>
              <span className="font-medium">{a.name}</span>
              <span className="text-xs text-slate-600">{a.model_id ?? 'unknown model'}{a.suite ? ` · ${a.suite}` : ''}</span>
            </div>
            <p className="mt-1 text-slate-800">{a.message}</p>
            <p className="mt-1 text-xs text-slate-600">
              {(a.previous_mean * 100).toFixed(1)}% → {(a.latest_mean * 100).toFixed(1)}% · p = {a.testable ? formatPValue(a.p_value) : NA}
              {a.ci ? ` · CI of difference [${a.ci[0].toFixed(3)}, ${a.ci[1].toFixed(3)}]` : ''}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ---------------------------------------------------------------- comparison
export function ComparePanel({ options, filters }: { options: Overview['options']; filters: Filters }) {
  const [mode, setMode] = useState<'model_id' | 'run_id'>('model_id');
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [res, setRes] = useState<CompareResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const items = mode === 'model_id' ? options.model_ids.map((v) => ({ v, l: v })) : options.runs.map((r) => ({ v: r.id, l: `${r.model_id ?? 'run'} · ${r.suite ?? '—'} · ${new Date(r.created_at).toLocaleDateString()} (${r.id.slice(0, 6)})` }));
  const run = async () => {
    setLoading(true); setErr(null);
    try { setRes(await fetchCompare({ a: { [mode]: a }, b: { [mode]: b } }, filters)); }
    catch (e) { setErr(e instanceof Error ? e.message : 'Comparison failed'); setRes(null); }
    finally { setLoading(false); }
  };
  const fmt = (d: { mean: number | null; n: number }) => (d.mean === null ? NA : `${(d.mean * 100).toFixed(1)}% (n=${d.n})`);
  return (
    <section className="card" aria-label="Side-by-side comparison">
      <h3 className="text-sm font-semibold">Side-by-side comparison</h3>
      <p className="mb-3 text-xs text-slate-600">Compare two models or two runs. Differences use a Welch t-test; metrics lacking data show N/A with the reason.</p>
      <div className="grid gap-3 sm:grid-cols-4">
        <div>
          <label className="label" htmlFor="cmp-mode">Compare</label>
          <select id="cmp-mode" className="input" value={mode} onChange={(e) => { setMode(e.target.value as 'model_id' | 'run_id'); setA(''); setB(''); setRes(null); }}>
            <option value="model_id">Two models</option><option value="run_id">Two runs</option>
          </select>
        </div>
        <div><label className="label" htmlFor="cmp-a">A (baseline)</label><select id="cmp-a" className="input" value={a} onChange={(e) => setA(e.target.value)}><option value="">Select…</option>{items.map((i) => <option key={i.v} value={i.v}>{i.l}</option>)}</select></div>
        <div><label className="label" htmlFor="cmp-b">B (candidate)</label><select id="cmp-b" className="input" value={b} onChange={(e) => setB(e.target.value)}><option value="">Select…</option>{items.map((i) => <option key={i.v} value={i.v}>{i.l}</option>)}</select></div>
        <div className="flex items-end"><button type="button" className="btn-primary w-full" disabled={!a || !b || a === b || loading} onClick={run}>{loading ? 'Comparing…' : 'Compare'}</button></div>
      </div>
      {err && <div className="mt-3"><Notice tone="error">{err}</Notice></div>}
      {res && (
        <div className="mt-4 overflow-x-auto">
          <p className="mb-2 text-sm">Quality index — A: <b>{res.a.quality_index.value === null ? NA : res.a.quality_index.value.toFixed(1)}</b> · B: <b>{res.b.quality_index.value === null ? NA : res.b.quality_index.value.toFixed(1)}</b></p>
          <table className="min-w-full divide-y divide-slate-200">
            <caption className="sr-only">Per-metric comparison of A and B</caption>
            <thead><tr>{['Metric', 'A mean', 'B mean', 'Δ (B−A)', 'p-value', '95% CI of Δ', 'Notes'].map((h) => <th key={h} scope="col" className="th">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-100">
              {res.metrics.map((m) => (
                <tr key={m.key}>
                  <th scope="row" className="td text-left font-medium">{m.name}</th>
                  <td className="td">{fmt(m.a)}</td><td className="td">{fmt(m.b)}</td>
                  <td className="td">{m.delta === null ? NA : `${m.delta >= 0 ? '+' : ''}${(m.delta * 100).toFixed(1)} pp`}</td>
                  <td className="td">{m.test?.testable ? <span className={m.test.significant ? 'font-semibold text-red-700' : ''}>{formatPValue(m.test.p_value)}</span> : NA}</td>
                  <td className="td">{m.test?.testable && m.test.ci_low !== undefined && m.test.ci_high !== undefined ? `[${(m.test.ci_low * 100).toFixed(1)}, ${(m.test.ci_high * 100).toFixed(1)}] pp` : NA}</td>
                  <td className="td text-xs text-slate-700">{m.na_reason ?? (m.test && !m.test.testable ? m.test.reason : m.test?.significant ? 'Significant difference' : '')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
