'use client';

import React, { useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import { Notice } from '@/components/ui/Notice';
import { reportPdfUrl } from '@/lib/api';
import { formatBytes } from '@/lib/format';
import { slug, triggerDownload } from '@/lib/download';

export function PdfPreview({ reportId, title }: { reportId: string; title: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [size, setSize] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;
    setUrl(null);
    setError(null);
    reportPdfUrl(reportId)
      .then((r) => {
        if (cancelled) return URL.revokeObjectURL(r.url);
        revoked = r.url;
        setUrl(r.url);
        setSize(r.size);
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : 'Could not load the PDF'));
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [reportId]);

  if (error) return <Notice tone="error">PDF could not be loaded: {error}</Notice>;
  if (!url) return <p className="text-sm text-slate-600">Loading PDF…</p>;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-600">PDF · {formatBytes(size)}</p>
        <button type="button" className="btn-primary" onClick={() => triggerDownload(url, `${slug(title)}.pdf`)}>
          <Download size={16} aria-hidden="true" /> Download PDF
        </button>
      </div>
      <iframe src={url} title={`PDF preview of ${title}`} className="h-[70vh] w-full rounded border border-slate-300 bg-white" />
    </div>
  );
}
