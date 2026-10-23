'use client';

import React, { Suspense, useState } from 'react';
import { Menu } from 'lucide-react';
import { Sidebar } from './Sidebar';
import { Modal } from './ui/Modal';

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="min-h-screen md:flex">
      <div className="sticky top-0 hidden h-screen shrink-0 md:block">
        <Suspense fallback={<div className="h-full w-64 bg-slate-900" />}>
          <Sidebar />
        </Suspense>
      </div>
      <div className="flex items-center justify-between bg-slate-900 px-4 py-3 text-white md:hidden">
        <span className="font-bold">
          EvalForge AI <span className="rounded bg-teal-950 px-1.5 py-0.5 text-xs text-teal-300">3.0</span>
        </span>
        <button type="button" className="rounded p-2 hover:bg-slate-800" aria-label="Open navigation" onClick={() => setOpen(true)}>
          <Menu size={20} />
        </button>
      </div>
      <Modal open={open} onClose={() => setOpen(false)} title="Navigation" side>
        <div className="-m-5 h-full">
          <Suspense fallback={null}>
            <Sidebar onNavigate={() => setOpen(false)} />
          </Suspense>
        </div>
      </Modal>
      <main className="min-w-0 flex-1 p-4 md:p-8">{children}</main>
    </div>
  );
}
