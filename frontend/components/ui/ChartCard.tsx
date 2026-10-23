import React from 'react';

interface ChartCardProps {
  title: string;
  description: string;
  empty?: string | null;
  height?: number;
  headerExtra?: React.ReactNode;
  table?: { headers: string[]; rows: (string | number)[][] };
  children: React.ReactNode;
  className?: string;
}

/** Chart container with title, accessible description and a visually hidden data table. */
export function ChartCard({ title, description, empty, height = 260, headerExtra, table, children, className = '' }: ChartCardProps) {
  return (
    <section className={`card ${className}`} aria-label={title}>
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          <p className="text-xs text-slate-600">{description}</p>
        </div>
        {headerExtra}
      </div>
      {empty ? (
        <p className="flex items-center justify-center rounded border border-dashed border-slate-300 bg-slate-50 px-3 text-center text-sm text-slate-600" style={{ minHeight: height }}>
          {empty}
        </p>
      ) : (
        <>
          <div role="img" aria-label={`${title}. ${description}`} style={{ height }} className="w-full">
            {children}
          </div>
          {table && (
            <table className="sr-only">
              <caption>{`${title} data`}</caption>
              <thead>
                <tr>
                  {table.headers.map((h) => (
                    <th key={h} scope="col">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((r, i) => (
                  <tr key={i}>
                    {r.map((c, j) => (
                      <td key={j}>{c}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
