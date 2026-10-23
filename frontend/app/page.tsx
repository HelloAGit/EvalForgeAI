'use client';

import React, { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { ConnectGate, useAuth } from '@/components/AuthProvider';
import { KpiCard } from '@/components/MetricCard';
import { Notice } from '@/components/ui/Notice';
import {
  AgentOutcomes, CiChart, Distributions, FailureChart, LatencyChart, LlmPerformance, ModelRanking, RagQuality,
  RegressionChart, TrendChart, UsageChart,
} from '@/components/dashboard/Charts';
import {
  AlertsPanel, ComparePanel, ConfigureButton, ConfigureKpis, FilterBar, KpiDrawer, LiveHeader, MubitBanner, QualityIndexCard,
} from '@/components/dashboard/Panels';
import { useLiveOverview } from '@/hooks/useLiveOverview';
import { API_BASE, fetchPreferences } from '@/lib/api';
import type { Filters, Preferences } from '@/lib/types';

const DEFAULT_PREFS: Preferences = { visible_kpis: [], default_filters: {}, auto_refresh: true };

function Dashboard() {
  const { token } = useAuth();
  const params = useSearchParams();
  const urlCategory = params.get('category') || undefined;
  const [filters, setFilters] = useState<Filters>({ category: urlCategory });
  const [prefs, setPrefs] = useState<Preferences>(DEFAULT_PREFS);
  const [prefsLoaded, setPrefsLoaded] = useState(false);
  const [prefsError, setPrefsError] = useState<string | null>(null);
  const [drawerKey, setDrawerKey] = useState<string | null>(null);
  const [configOpen, setConfigOpen] = useState(false);

  useEffect(() => {
    setFilters((f) => (f.category === urlCategory ? f : { ...f, category: urlCategory }));
  }, [urlCategory]);

  useEffect(() => {
    if (!token) {
      setPrefsLoaded(false);
      return;
    }
    let live = true;
    fetchPreferences()
      .then((p) => live && (setPrefs({ ...DEFAULT_PREFS, ...p }), setPrefsError(null)))
      .catch((e: unknown) => live && setPrefsError(e instanceof Error ? e.message : 'Could not load preferences'))
      .finally(() => live && setPrefsLoaded(true));
    return () => {
      live = false;
    };
  }, [token]);

  const { overview, live, paused, pause, resume } = useLiveOverview(filters, !!token && prefsLoaded, !prefs.auto_refresh);
  const refreshKey = overview?.last_event_id ?? 0;
  const visible = prefs.visible_kpis.length ? new Set(prefs.visible_kpis) : null;
  const kpis = overview?.kpis ?? [];
  const gridKpis = kpis.filter((k) => k.key !== 'quality_index' && (!visible || visible.has(k.key)));

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">AI Quality Intelligence Command Centre</h1>
          <p className="text-sm text-slate-600">Continuous AI quality monitoring and statistical validation from persisted evaluation data.</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <LiveHeader live={live} paused={paused} onPause={pause} onResume={resume} />
          <MubitBanner enabled={!!token} />
        </div>
      </header>

      {prefsError && <Notice tone="warning">Preferences could not be loaded ({prefsError}); showing defaults.</Notice>}
      {live.status === 'unauthorized' && <Notice tone="error">The API rejected the token. Reconnect to continue.</Notice>}
      {live.error && !overview && live.status !== 'unauthorized' && <Notice tone="error">Could not load the dashboard: {live.error}</Notice>}

      {!overview ? (
        !live.error && <p className="text-sm text-slate-600">Loading dashboard…</p>
      ) : (
        <>
          <FilterBar options={overview.options} filters={filters} onChange={setFilters} />
          {!overview.has_data ? (
            <section className="card" aria-label="No data">
              <h2 className="text-lg font-semibold">No evaluation data{Object.values(filters).some(Boolean) ? ' matches these filters' : ' yet'}</h2>
              <p className="mt-1 text-sm text-slate-700">
                The dashboard only shows persisted results. Ingest an evaluation run to populate it
                {Object.values(filters).some(Boolean) ? ' (or clear the filters)' : ''}:
              </p>
              <pre className="mt-3 overflow-x-auto rounded bg-slate-900 p-3 text-xs text-slate-100">{`curl -X POST ${API_BASE}/api/v1/evaluations/runs \\
  -H "Authorization: Bearer $EVALFORGE_API_TOKEN" -H "Content-Type: application/json" \\
  -d '{"project_id": "<project id>", "model_id": "my-model", "category": "llm", "complete": true,
       "results": [{"sample_id": "s1", "metrics": {"answer_correctness": 1.0}, "latency_ms": 420}]}'`}</pre>
              <p className="mt-2 text-xs text-slate-600">Create a project first with POST /api/v1/projects. New data appears here live.</p>
            </section>
          ) : (
            <>
              <QualityIndexCard qi={overview.quality_index} onOpen={() => setDrawerKey('quality_index')} />
              <section aria-label="Key performance indicators">
                <div className="mb-2 flex items-center justify-between">
                  <h2 className="text-lg font-semibold">Key indicators</h2>
                  <ConfigureButton onClick={() => setConfigOpen(true)} />
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {gridKpis.map((k) => (
                    <KpiCard key={k.key} kpi={k} onOpen={setDrawerKey} />
                  ))}
                </div>
              </section>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <TrendChart filters={filters} kpis={kpis} refreshKey={refreshKey} />
                <ModelRanking charts={overview.charts} />
                <AlertsPanel filters={filters} refreshKey={refreshKey} enabled={!!token} />
                <LlmPerformance charts={overview.charts} />
                <RagQuality charts={overview.charts} />
                <AgentOutcomes charts={overview.charts} />
                <Distributions charts={overview.charts} />
                <LatencyChart charts={overview.charts} />
                <UsageChart charts={overview.charts} />
                <RegressionChart charts={overview.charts} />
                <CiChart charts={overview.charts} />
                <FailureChart charts={overview.charts} />
              </div>
              <ComparePanel options={overview.options} filters={filters} />
            </>
          )}
          <ConfigureKpis open={configOpen} onClose={() => setConfigOpen(false)} kpis={kpis} prefs={prefs} onSaved={setPrefs} />
          <KpiDrawer metricKey={drawerKey} filters={filters} onClose={() => setDrawerKey(null)} />
        </>
      )}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <ConnectGate>
      <Suspense fallback={<p className="text-sm text-slate-600">Loading…</p>}>
        <Dashboard />
      </Suspense>
    </ConnectGate>
  );
}
