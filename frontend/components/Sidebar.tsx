'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { LayoutDashboard, Brain, Database, Cpu, FileText, Library, Video, CalendarClock, KeyRound, LogOut } from 'lucide-react';
import { useAuth } from './AuthProvider';

interface Item {
  href: string;
  label: string;
  icon: React.ReactNode;
  path: string;
  category?: string;
}

const groups: { title?: string; items: Item[] }[] = [
  {
    items: [
      { href: '/', label: 'Dashboard', icon: <LayoutDashboard size={18} />, path: '/' },
      { href: '/?category=llm', label: 'LLM Evaluation', icon: <Brain size={18} />, path: '/', category: 'llm' },
      { href: '/?category=rag', label: 'RAG Intelligence', icon: <Database size={18} />, path: '/', category: 'rag' },
      { href: '/?category=agent', label: 'Agent Diagnostics', icon: <Cpu size={18} />, path: '/', category: 'agent' },
    ],
  },
  {
    title: 'Reports',
    items: [
      { href: '/reports', label: 'Report Builder', icon: <FileText size={18} />, path: '/reports' },
      { href: '/reports/library', label: 'Report Library', icon: <Library size={18} />, path: '/reports/library' },
    ],
  },
  {
    title: 'Media',
    items: [{ href: '/videos', label: 'Video Studio', icon: <Video size={18} />, path: '/videos' }],
  },
  {
    title: 'Admin',
    items: [{ href: '/schedules', label: 'Schedules', icon: <CalendarClock size={18} />, path: '/schedules' }],
  },
];

export const Sidebar = ({ onNavigate }: { onNavigate?: () => void }) => {
  const pathname = usePathname();
  const params = useSearchParams();
  const category = params.get('category');
  const { token, ready, openConnect, disconnect } = useAuth();

  const isActive = (i: Item) => {
    if (pathname !== i.path) return false;
    if (i.path === '/') return (i.category ?? null) === category;
    return true;
  };

  return (
    <aside className="flex h-full w-64 flex-col bg-slate-900 text-slate-300">
      <div className="border-b border-slate-800 p-5">
        <h1 className="text-xl font-bold tracking-wide text-white">
          EvalForge AI{' '}
          <span className="rounded border border-teal-800 bg-teal-950 px-1.5 py-0.5 text-xs text-teal-300">3.0</span>
        </h1>
        <p className="mt-1 text-xs text-slate-400">Evidence-Based Intelligence</p>
      </div>
      <nav aria-label="Primary" className="flex-1 space-y-4 overflow-y-auto p-4">
        {groups.map((g, gi) => (
          <div key={gi}>
            {g.title && <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">{g.title}</p>}
            <ul className="space-y-1">
              {g.items.map((i) => {
                const active = isActive(i);
                return (
                  <li key={i.href}>
                    <Link
                      href={i.href}
                      onClick={onNavigate}
                      aria-current={active ? 'page' : undefined}
                      className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium ${
                        active ? 'bg-slate-800 text-white' : 'hover:bg-slate-800 hover:text-white'
                      }`}
                    >
                      {i.icon} {i.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
      <div className="border-t border-slate-800 p-4">
        {ready && token ? (
          <button type="button" onClick={disconnect} className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-slate-300 hover:bg-slate-800 hover:text-white">
            <LogOut size={18} aria-hidden="true" /> Disconnect
          </button>
        ) : (
          <button type="button" onClick={openConnect} className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-amber-300 hover:bg-slate-800">
            <KeyRound size={18} aria-hidden="true" /> Connect
          </button>
        )}
      </div>
    </aside>
  );
};
