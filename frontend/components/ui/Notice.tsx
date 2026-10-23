import React from 'react';
import { AlertTriangle, Info, XCircle } from 'lucide-react';

type Tone = 'error' | 'warning' | 'info';
const styles: Record<Tone, string> = {
  error: 'border-red-300 bg-red-50 text-red-800',
  warning: 'border-amber-300 bg-amber-50 text-amber-900',
  info: 'border-slate-300 bg-white text-slate-700',
};

export function Notice({ tone = 'info', children, action }: { tone?: Tone; children: React.ReactNode; action?: React.ReactNode }) {
  const Icon = tone === 'error' ? XCircle : tone === 'warning' ? AlertTriangle : Info;
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`flex items-start gap-3 rounded-md border px-4 py-3 text-sm ${styles[tone]}`}>
      <Icon size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div className="flex-1">{children}</div>
      {action}
    </div>
  );
}
