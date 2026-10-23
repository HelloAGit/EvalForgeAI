import React from 'react';

interface MetricCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: string;
  type?: 'neutral' | 'success' | 'warning';
}

export const MetricCard: React.FC<MetricCardProps> = ({ title, value, subtitle, trend, type = 'neutral' }) => {
  const borderColor = type === 'success' ? 'border-teal-500' : type === 'warning' ? 'border-amber-500' : 'border-slate-200';
  
  return (
    <div className={`bg-white p-5 rounded-lg border-t-4 ${borderColor} shadow-sm border-x border-b border-slate-200`}>
      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">{title}</p>
      <div className="flex items-baseline justify-between mt-2">
        <h3 className="text-2xl font-bold text-slate-900">{value}</h3>
        {trend && <span className="text-xs font-medium text-teal-600 bg-teal-50 px-2 py-0.5 rounded">{trend}</span>}
      </div>
      {subtitle && <p className="text-xs text-slate-400 mt-1">{subtitle}</p>}
    </div>
  );
};
