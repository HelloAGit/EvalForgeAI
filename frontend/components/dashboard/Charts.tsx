'use client';

import React, { useEffect, useMemo, useState } from 'react';
import {
  Bar, BarChart, CartesianGrid, ComposedChart, ErrorBar, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { ChartCard } from '@/components/ui/ChartCard';
import { fetchTrends } from '@/lib/api';
import { NA, formatValue, pct } from '@/lib/format';
import type { Charts, Filters, Kpi, Trends } from '@/lib/types';

export const COLORS = ['#0f766e', '#2563eb', '#d97706', '#7c3aed', '#dc2626', '#0891b2', '#65a30d', '#be185d'];
const TEAL = '#0f766e';
const RED = '#b91c1c';
const AMBER = '#b45309';
const SLATE = '#64748b';
const AXIS = { fontSize: 11, fill: '#475569' };

const pctFmt = (v: unknown) => (typeof v === 'number' ? `${v.toFixed(1)}%` : NA);
const cell = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? NA : Number(v.toFixed(d)));

const LLM_KEYS: [string, string][] = [
  ['llm_correctness', 'Correctness'],
  ['factual_precision', 'Factual precision'],
  ['hallucination_rate', 'Hallucination rate (lower is better)'],
  ['instruction_adherence', 'Instruction adherence'],
  ['response_consistency', 'Consistency'],
];
const RAG_KEYS: [string, string, 'retrieval' | 'generation'][] = [
  ['context_precision', 'Context precision', 'retrieval'],
  ['context_recall', 'Context recall', 'retrieval'],
  ['retrieval_ndcg', 'NDCG@K', 'retrieval'],
  ['rag_faithfulness', 'Faithfulness', 'generation'],
  ['answer_relevancy', 'Answer relevancy', 'generation'],
  ['citation_accuracy', 'Citation accuracy', 'generation'],
];

const NO_FILTER = 'No data for the current filters.';

export function ModelRanking({ charts }: { charts: Charts }) {
  const rows = charts.model_ranking;
  return (
    <section className="card" aria-label="Model ranking leaderboard">
      <h3 className="text-sm font-semibold">Model ranking leaderboard</h3>
      <p className="mb-2 text-xs text-slate-600">Models ranked by Overall AI Quality Index. Models without enough metric coverage show N/A and are unranked.</p>
      {rows.length === 0 ? (
        <p className="rounded border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">{NO_FILTER}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200">
            <caption className="sr-only">Model ranking by quality index</caption>
            <thead>
              <tr>
                <th scope="col" className="th">Rank</th>
                <th scope="col" className="th">Model</th>
                <th scope="col" className="th">Quality index</th>
                <th scope="col" className="th">Coverage</th>
                <th scope="col" className="th">Metrics</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={r.model_id}>
                  <td className="td">{r.rank ?? '—'}</td>
                  <td className="td font-medium">{r.model_id}</td>
                  <td className="td">
                    {r.quality_index === null ? (
                      <span className="text-amber-800" title={r.na_reason ?? undefined}>
                        {NA}
                        {r.na_reason ? <span className="ml-2 text-xs text-slate-600">{r.na_reason}</span> : null}
                      </span>
                    ) : (
                      <span className="font-semibold text-teal-800">{r.quality_index.toFixed(1)}</span>
                    )}
                  </td>
                  <td className="td">{(r.coverage * 100).toFixed(0)}%</td>
                  <td className="td">{r.n_metrics}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function TrendChart({ filters, kpis, refreshKey }: { filters: Filters; kpis: Kpi[]; refreshKey: number }) {
  const [metric, setMetric] = useState('quality_index');
  const [bucket, setBucket] = useState<'day' | 'hour'>('day');
  const [data, setData] = useState<Trends | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fkey = JSON.stringify(filters);

  const options = useMemo(() => {
    const ops = ['latency_p95', 'latency_median', 'tokens', 'cost', 'runs', 'failure_rate', 'results'];
    const qual = kpis.filter((k) => ['llm', 'rag', 'agent'].includes(k.category)).map((k) => ({ v: k.key, l: k.name }));
    return [
      { v: 'quality_index', l: 'Overall quality index' },
      ...qual,
      ...ops.map((o) => ({ v: o, l: o.replace('_', ' ') })),
    ];
  }, [kpis]);

  useEffect(() => {
    const ac = new AbortController();
    fetchTrends(JSON.parse(fkey) as Filters, metric, bucket, ac.signal)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => {
        if (ac.signal.aborted) return;
        setError(e instanceof Error ? e.message : 'Failed to load trend');
      });
    return () => ac.abort();
  }, [fkey, metric, bucket, refreshKey]);

  const unit = data?.unit ?? 'ratio';
  const { rows, models } = useMemo(() => {
    const byT = new Map<string, Record<string, number | string>>();
    const ms: string[] = [];
    for (const s of data?.series ?? []) {
      ms.push(s.model_id);
      for (const p of s.points) {
        const row = byT.get(p.t) ?? { t: p.t };
        row[s.model_id] = unit === 'ratio' ? p.value * 100 : p.value;
        byT.set(p.t, row);
      }
    }
    return { rows: Array.from(byT.values()).sort((a, b) => String(a.t).localeCompare(String(b.t))), models: ms };
  }, [data, unit]);

  const label = (t: unknown) => {
    const s = String(t);
    return bucket === 'hour' ? s.slice(5, 13).replace('T', ' ') + 'h' : s.slice(0, 10);
  };
  const fmt = (v: unknown) => (typeof v === 'number' ? formatValue(unit === 'ratio' ? v / 100 : v, unit) : NA);
  const empty = error ? `Could not load trend: ${error}` : data === null ? 'Loading trend…' : rows.length === 0 ? data.na_reason ?? NO_FILTER : null;

  return (
    <ChartCard
      title="Multi-model quality trend"
      description={`Trend of the selected metric per model, bucketed by ${bucket}.`}
      empty={empty}
      className="lg:col-span-2"
      height={300}
      headerExtra={
        <div className="flex gap-2">
          <label className="sr-only" htmlFor="trend-metric">Trend metric</label>
          <select id="trend-metric" className="input !w-auto !py-1" value={metric} onChange={(e) => setMetric(e.target.value)}>
            {options.map((o) => (
              <option key={o.v} value={o.v}>{o.l}</option>
            ))}
          </select>
          <label className="sr-only" htmlFor="trend-bucket">Bucket</label>
          <select id="trend-bucket" className="input !w-auto !py-1" value={bucket} onChange={(e) => setBucket(e.target.value as 'day' | 'hour')}>
            <option value="day">Day</option>
            <option value="hour">Hour</option>
          </select>
        </div>
      }
      table={{ headers: ['Time', ...models], rows: rows.map((r) => [label(r.t), ...models.map((m) => cell(r[m] as number | undefined, 2))]) }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="t" tickFormatter={label} tick={AXIS} />
          <YAxis tick={AXIS} tickFormatter={(v: number) => (unit === 'ratio' ? `${v}%` : String(v))} />
          <Tooltip labelFormatter={label} formatter={fmt} />
          <Legend />
          {models.map((m, i) => (
            <Line key={m} type="monotone" dataKey={m} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot connectNulls />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function LlmPerformance({ charts }: { charts: Charts }) {
  const data = charts.llm_performance.map((r) => ({
    model: r.model_id,
    ...Object.fromEntries(LLM_KEYS.map(([k]) => [k, pct(r[k] as number | null)])),
  }));
  return (
    <ChartCard
      title="LLM performance by model"
      description="Mean score per LLM metric and model (percent). Missing metrics are omitted and listed as N/A in the data table."
      empty={data.length ? null : NO_FILTER}
      table={{ headers: ['Model', ...LLM_KEYS.map(([, l]) => l)], rows: data.map((d) => [d.model, ...LLM_KEYS.map(([k]) => cell((d as Record<string, number | null | string>)[k] as number | null))]) }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="model" tick={AXIS} />
          <YAxis domain={[0, 100]} tick={AXIS} tickFormatter={(v: number) => `${v}%`} />
          <Tooltip formatter={pctFmt} />
          <Legend />
          {LLM_KEYS.map(([k, l], i) => (
            <Bar key={k} dataKey={k} name={l} fill={COLORS[i % COLORS.length]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function RagQuality({ charts }: { charts: Charts }) {
  const data = charts.rag_quality.map((r) => ({
    model: r.model_id,
    ...Object.fromEntries(RAG_KEYS.map(([k, , g]) => [k, pct((g === 'retrieval' ? r.retrieval : r.generation)[k])])),
  }));
  const shades = { retrieval: ['#0f766e', '#14b8a6', '#5eead4'], generation: ['#1d4ed8', '#3b82f6', '#93c5fd'] };
  return (
    <ChartCard
      title="RAG: retrieval vs generation"
      description="Retrieval metrics (teal) compared with generation metrics (blue) per model, in percent."
      empty={data.length ? null : NO_FILTER}
      table={{ headers: ['Model', ...RAG_KEYS.map(([, l]) => l)], rows: data.map((d) => [d.model, ...RAG_KEYS.map(([k]) => cell((d as Record<string, number | null | string>)[k] as number | null))]) }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="model" tick={AXIS} />
          <YAxis domain={[0, 100]} tick={AXIS} tickFormatter={(v: number) => `${v}%`} />
          <Tooltip formatter={pctFmt} />
          <Legend />
          {RAG_KEYS.map(([k, l, g]) => (
            <Bar key={k} dataKey={k} name={`${l} (${g})`} fill={shades[g][RAG_KEYS.filter((x) => x[2] === g).findIndex((x) => x[0] === k)]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function AgentOutcomes({ charts }: { charts: Charts }) {
  const data = charts.agent_outcomes;
  return (
    <ChartCard
      title="Agent success / failure distribution"
      description="Count of agent results per model by outcome: success, failure (FAILED or ERROR) and unjudged."
      empty={data.length ? null : NO_FILTER}
      table={{ headers: ['Model', 'Success', 'Failure', 'Unjudged'], rows: data.map((d) => [d.model_id, d.success, d.failure, d.unjudged]) }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="model_id" tick={AXIS} />
          <YAxis allowDecimals={false} tick={AXIS} />
          <Tooltip />
          <Legend />
          <Bar dataKey="success" name="Success" stackId="a" fill={TEAL} />
          <Bar dataKey="failure" name="Failure" stackId="a" fill={RED} />
          <Bar dataKey="unjudged" name="Unjudged" stackId="a" fill={SLATE} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function Distributions({ charts }: { charts: Charts }) {
  const dists = charts.distributions;
  const [key, setKey] = useState('');
  const sel = dists.find((d) => d.metric_key === key) ?? dists[0];
  const data = sel ? sel.counts.map((c, i) => ({ bin: `${sel.bins[i].toFixed(1)}–${(sel.bins[i] + 0.1).toFixed(1)}`, count: c })) : [];
  return (
    <ChartCard
      title="Metric score distribution"
      description="Histogram of observed scores (0–1, ten bins) for the selected metric."
      empty={sel ? null : NO_FILTER}
      headerExtra={
        dists.length > 0 ? (
          <>
            <label className="sr-only" htmlFor="dist-metric">Distribution metric</label>
            <select id="dist-metric" className="input !w-auto !py-1" value={sel?.metric_key ?? ''} onChange={(e) => setKey(e.target.value)}>
              {dists.map((d) => (
                <option key={d.metric_key} value={d.metric_key}>{d.name}</option>
              ))}
            </select>
          </>
        ) : null
      }
      table={{ headers: ['Score bin', 'Observations'], rows: data.map((d) => [d.bin, d.count]) }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="bin" tick={AXIS} />
          <YAxis allowDecimals={false} tick={AXIS} />
          <Tooltip />
          <Legend />
          <Bar dataKey="count" name="Observations" fill={TEAL} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function LatencyChart({ charts }: { charts: Charts }) {
  const data = charts.latency_percentiles;
  return (
    <ChartCard
      title="Latency percentiles"
      description="Median (p50), p95 and p99 response latency per model, in milliseconds."
      empty={data.length ? null : 'No latency recorded for the current filters.'}
      table={{ headers: ['Model', 'N', 'p50 ms', 'p95 ms', 'p99 ms'], rows: data.map((d) => [d.model_id, d.n, cell(d.p50, 0), cell(d.p95, 0), cell(d.p99, 0)]) }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="model_id" tick={AXIS} />
          <YAxis tick={AXIS} unit=" ms" />
          <Tooltip formatter={(v: unknown) => (typeof v === 'number' ? `${Math.round(v)} ms` : NA)} />
          <Legend />
          <Bar dataKey="p50" name="p50" fill={TEAL} />
          <Bar dataKey="p95" name="p95" fill={AMBER} />
          <Bar dataKey="p99" name="p99" fill={RED} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function UsageChart({ charts }: { charts: Charts }) {
  const data = charts.usage;
  return (
    <ChartCard
      title="API / token usage and cost"
      description="Recorded tokens (bars, left axis) and cost in USD (line, right axis) per model. Models without recorded values show gaps."
      empty={data.length ? null : NO_FILTER}
      table={{ headers: ['Model', 'Results', 'Tokens', 'Cost USD'], rows: data.map((d) => [d.model_id, d.results, d.tokens ?? NA, d.cost_usd === null ? NA : d.cost_usd.toFixed(4)]) }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="model_id" tick={AXIS} />
          <YAxis yAxisId="l" tick={AXIS} />
          <YAxis yAxisId="r" orientation="right" tick={AXIS} tickFormatter={(v: number) => `$${v}`} />
          <Tooltip />
          <Legend />
          <Bar yAxisId="l" dataKey="tokens" name="Tokens" fill={TEAL} />
          <Line yAxisId="r" dataKey="cost_usd" name="Cost (USD)" stroke={AMBER} strokeWidth={2} />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function RegressionChart({ charts }: { charts: Charts }) {
  const data = charts.regression.map((r) => ({
    label: `${r.name} · ${r.model_id}`,
    previous: pct(r.previous),
    latest: pct(r.latest),
    severity: r.severity,
  }));
  return (
    <ChartCard
      title="Regression comparison"
      description="Previous versus latest run mean for metrics that regressed beyond the alert threshold (percent)."
      empty={data.length ? null : 'No regressions detected against the previous comparable run.'}
      table={{ headers: ['Metric · model', 'Previous %', 'Latest %', 'Severity'], rows: data.map((d) => [d.label, cell(d.previous), cell(d.latest), d.severity]) }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="label" tick={AXIS} interval={0} />
          <YAxis domain={[0, 100]} tick={AXIS} tickFormatter={(v: number) => `${v}%`} />
          <Tooltip formatter={pctFmt} />
          <Legend />
          <Bar dataKey="previous" name="Previous run" fill={SLATE} />
          <Bar dataKey="latest" name="Latest run" fill={RED} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function CiChart({ charts }: { charts: Charts }) {
  const data = charts.confidence_intervals.map((c) => ({
    name: c.name,
    mean: c.mean * 100,
    lo: c.ci_low * 100,
    hi: c.ci_high * 100,
    n: c.n,
    err: [(c.mean - c.ci_low) * 100, (c.ci_high - c.mean) * 100] as [number, number],
  }));
  return (
    <ChartCard
      title="Confidence intervals"
      description="Mean score per metric with 95% confidence interval error bars (percent). Only metrics with enough observations are shown."
      empty={data.length ? null : 'No metric has enough observations for a confidence interval.'}
      table={{ headers: ['Metric', 'Mean %', 'CI low %', 'CI high %', 'N'], rows: data.map((d) => [d.name, cell(d.mean, 2), cell(d.lo, 2), cell(d.hi, 2), d.n]) }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="name" tick={AXIS} interval={0} />
          <YAxis domain={[0, 100]} tick={AXIS} tickFormatter={(v: number) => `${v}%`} />
          <Tooltip formatter={pctFmt} />
          <Legend />
          <Bar dataKey="mean" name="Mean (95% CI)" fill="#5eead4">
            <ErrorBar dataKey="err" width={6} stroke="#0f172a" strokeWidth={2} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function FailureChart({ charts }: { charts: Charts }) {
  const data = charts.failure_classification;
  return (
    <ChartCard
      title="Failure classification"
      description="Failed or errored results grouped by recorded error type."
      empty={data.length ? null : 'No failed results for the current filters.'}
      table={{ headers: ['Classification', 'Count'], rows: data.map((d) => [d.classification, d.count]) }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 24 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis type="number" allowDecimals={false} tick={AXIS} />
          <YAxis type="category" dataKey="classification" width={140} tick={AXIS} />
          <Tooltip />
          <Legend />
          <Bar dataKey="count" name="Failures" fill={RED} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
