import React from 'react';
import { NA, formatCi, formatValue } from '@/lib/format';
import type { Kpi } from '@/lib/types';

interface KpiCardProps {
  kpi: Kpi;
  onOpen: (key: string) => void;
}

const ACCENT: Record<string, string> = {
  llm: 'border-t-teal-600',
  rag: 'border-t-teal-600',
  agent: 'border-t-teal-600',
  operations: 'border-t-slate-400',
};

export const KpiCard: React.FC<KpiCardProps> = ({ kpi, onOpen }) => {
  const na = kpi.value === null || kpi.status === 'na';
  const ci = formatCi(kpi.ci, kpi.unit);
  return (
    <button
      type="button"
      onClick={() => onOpen(kpi.key)}
      aria-label={`${kpi.name}: ${na ? `not available. ${kpi.na_reason ?? ''}` : formatValue(kpi.value, kpi.unit)}. Open details`}
      className={`flex h-full flex-col rounded-lg border border-slate-200 border-t-4 ${
        na ? 'border-t-amber-500' : ACCENT[kpi.category] ?? 'border-t-slate-400'
      } bg-white p-4 text-left shadow-sm hover:shadow-md`}
    >
      <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">{kpi.name}</span>
      <span className={`mt-2 text-2xl font-bold ${na ? 'text-amber-700' : 'text-slate-900'}`}>
        {na ? NA : formatValue(kpi.value, kpi.unit)}
      </span>
      {na ? (
        <span className="mt-1 line-clamp-3 text-xs text-slate-700" title={kpi.na_reason ?? undefined}>
          {kpi.na_reason ?? 'Not available.'}
        </span>
      ) : (
        <span className="mt-1 text-xs text-slate-600">
          n = {kpi.n_observations.toLocaleString('en-US')}
          {ci ? ` · 95% CI ${ci}` : ''}
        </span>
      )}
    </button>
  );
};
