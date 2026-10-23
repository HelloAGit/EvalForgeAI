'use client';

import React, { useEffect, useState } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { MetricCard } from '@/components/MetricCard';
import { fetchDashboardSummary, fetchMubitStatus } from '@/lib/api';
import { DashboardSummary, MubitStatus } from '@/lib/types';
import { CheckCircle2, AlertTriangle, ShieldCheck } from 'lucide-react';

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [mubit, setMubit] = useState<MubitStatus | null>(null);

  useEffect(() => {
    fetchDashboardSummary().then(setSummary);
    fetchMubitStatus().then(setMubit);
  }, []);

  return (
    <div className="flex bg-slate-50 min-h-screen">
      <Sidebar />
      <main className="flex-1 p-8">
        <header className="flex justify-between items-center mb-8">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Quality Intelligence Dashboard</h1>
            <p className="text-sm text-slate-500">Continuous AI quality monitoring and statistical validation</p>
          </div>
          
          <div className="flex items-center gap-3 bg-white px-4 py-2 rounded-lg border border-slate-200 text-xs font-medium">
            <span className="text-slate-500">Mubit Router:</span>
            {mubit?.connection_active ? (
              <span className="flex items-center gap-1.5 text-teal-600 font-semibold"><CheckCircle2 size={14} /> Connected</span>
            ) : (
              <span className="flex items-center gap-1.5 text-amber-600 font-semibold"><AlertTriangle size={14} /> Unconfigured / Simulation Mode</span>
            )}
          </div>
        </header>

        {summary?.is_demo_data && (
          <div className="mb-6 p-3 bg-amber-50 border border-amber-200 rounded-md text-xs text-amber-800 flex items-center gap-2">
            <AlertTriangle size={16} />
            <span><strong>Simulated Data Mode:</strong> Displaying benchmark demonstration data. Configure your Mubit API key to run live evaluations.</span>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <MetricCard title="Overall Quality Index" value={`${summary?.quality_index ?? '--'} / 100`} subtitle="Configurable composite weighted score" type="success" trend="+2.4%" />
          <MetricCard title="LLM Correctness" value={`${summary?.llm_correctness ?? '--'}%`} subtitle="Deterministic & model-judged" type="success" />
          <MetricCard title="RAG Faithfulness" value={`${summary?.rag_faithfulness ?? '--'}%`} subtitle="Context-grounded assertions" type="neutral" />
          <MetricCard title="Agent Completion" value={`${summary?.agent_completion ?? '--'}%`} subtitle="End-to-end task execution" type="neutral" />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <MetricCard title="Total Evaluation Runs" value={summary?.total_evaluations ?? '--'} subtitle="Across all projects" />
          <MetricCard title="Verified Failures" value={summary?.verified_failures ?? '--'} subtitle="Schema & correctness regressions" type="warning" />
          <MetricCard title="Average Latency" value={`${summary?.avg_latency_ms ?? '--'} ms`} subtitle="P95 execution latency" />
          <MetricCard title="Evaluation Cost" value={`$${summary?.eval_cost_usd ?? '--'}`} subtitle="Estimated token expenditure" />
        </div>

        <div className="bg-white p-6 rounded-lg border border-slate-200 shadow-sm">
          <h2 className="text-base font-bold text-slate-800 mb-2 flex items-center gap-2"><ShieldCheck className="text-teal-600" size={18} /> Evaluation Methodology Transparency</h2>
          <p className="text-xs text-slate-600 leading-relaxed">
            The Composite Quality Index is synthesized using normalized scores from deterministic exact matches, 
            RAG context precision, and decision-level agent completion. Missing data points are excluded using pairwise 
            deletion without imputing assumed success. All statistical significance assertions rely on paired t-tests 
            and McNemar test calculations.
          </p>
        </div>
      </main>
    </div>
  );
}
