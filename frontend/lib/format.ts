import type { Unit } from './types';

export const NA = 'N/A';

export function formatValue(value: number | null, unit: Unit): string {
  if (value === null) return NA;
  if (unit === 'ratio') return `${(value * 100).toFixed(1)}%`;
  if (unit === 'ms') return `${value.toLocaleString('en-US', { maximumFractionDigits: 0 })} ms`;
  if (unit === 'usd') return `$${value.toLocaleString('en-US', { minimumFractionDigits: value < 1 ? 4 : 2, maximumFractionDigits: value < 1 ? 4 : 2 })}`;
  if (unit === 'tokens' || unit === 'count') return value.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (unit === 'index') return value.toFixed(1);
  return value.toFixed(3);
}

export function formatCi(ci: [number, number] | null, unit: Unit): string | null {
  return ci ? `[${formatValue(ci[0], unit)}, ${formatValue(ci[1], unit)}]` : null;
}

export function formatClock(value: Date | null): string {
  return value && !Number.isNaN(value.getTime()) ? value.toLocaleTimeString('en-US') : '—';
}

export function formatDateTime(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? NA : date.toLocaleString('en-US');
}

export function formatPValue(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return NA;
  return value < 0.001 ? '<0.001' : value.toFixed(3);
}

export function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) return NA;
  if (value < 1024) return `${value} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let size = value / 1024;
  let unit = units[0];
  for (let i = 1; size >= 1024 && i < units.length; i += 1) {
    size /= 1024;
    unit = units[i];
  }
  return `${size.toFixed(1)} ${unit}`;
}

export function pct(value: number | null | undefined): number | null {
  return value == null ? null : value * 100;
}
