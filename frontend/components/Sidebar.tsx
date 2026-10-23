import React from 'react';
import Link from 'next/link';
import { LayoutDashboard, Brain, Database, ShieldAlert, Cpu, Settings, LineChart, FlaskConical } from 'lucide-react';

export const Sidebar = () => {
  return (
    <aside className="w-64 bg-slate-900 text-slate-300 flex flex-col min-h-screen">
      <div className="p-5 border-b border-slate-800">
        <h1 className="text-xl font-bold text-white tracking-wide">EvalForge AI <span className="text-teal-400 text-xs px-1.5 py-0.5 rounded bg-teal-950 border border-teal-800">2.0</span></h1>
        <p className="text-xs text-slate-400 mt-1">Evidence-Based Intelligence</p>
      </div>
      <nav className="flex-1 p-4 space-y-1">
        <Link href="/" className="flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md bg-slate-800 text-white"><LayoutDashboard size={18} /> Overview</Link>
        <Link href="/evaluations" className="flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md hover:bg-slate-800 hover:text-white"><Brain size={18} /> LLM Evaluation</Link>
        <Link href="/rag" className="flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md hover:bg-slate-800 hover:text-white"><Database size={18} /> RAG Intelligence</Link>
        <Link href="/agents" className="flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md hover:bg-slate-800 hover:text-white"><Cpu size={18} /> Agent Diagnostics</Link>
        <Link href="/statistics" className="flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md hover:bg-slate-800 hover:text-white"><LineChart size={18} /> Statistical Studio</Link>
        <Link href="/experiments" className="flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md hover:bg-slate-800 hover:text-white"><FlaskConical size={18} /> Experiments</Link>
      </nav>
      <div className="p-4 border-t border-slate-800">
        <Link href="/settings" className="flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md text-slate-400 hover:bg-slate-800 hover:text-white"><Settings size={18} /> Settings</Link>
      </div>
    </aside>
  );
};
