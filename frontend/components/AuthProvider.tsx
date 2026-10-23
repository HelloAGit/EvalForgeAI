'use client';

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { KeyRound } from 'lucide-react';
import { clearToken, getToken, setToken, subscribeToken } from '@/lib/auth';
import { API_BASE } from '@/lib/api';
import { Modal } from './ui/Modal';

interface AuthCtx {
  token: string | null;
  ready: boolean;
  openConnect: () => void;
  disconnect: () => void;
}

const Ctx = createContext<AuthCtx>({ token: null, ready: false, openConnect: () => undefined, disconnect: () => undefined });
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTok] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(false);
  const [rejected, setRejected] = useState(false);
  const [input, setInput] = useState('');
  const hadToken = useRef(false);

  useEffect(() => {
    const sync = () => {
      const t = getToken();
      if (!t && hadToken.current) setRejected(true);
      hadToken.current = !!t;
      setTok(t);
      if (!t) setOpen(true);
      else setOpen(false);
    };
    sync();
    setReady(true);
    return subscribeToken(sync);
  }, []);

  const openConnect = useCallback(() => setOpen(true), []);
  const disconnect = useCallback(() => {
    hadToken.current = false;
    clearToken();
    setRejected(false);
  }, []);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    setRejected(false);
    setToken(input);
    setInput('');
  };

  return (
    <Ctx.Provider value={{ token, ready, openConnect, disconnect }}>
      {children}
      <Modal open={open && ready} onClose={() => setOpen(false)} title="Connect to EvalForge API">
        <form onSubmit={submit} className="space-y-4">
          {rejected && (
            <p role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
              The API rejected the token (401). Enter a valid token to continue.
            </p>
          )}
          <p className="text-sm text-slate-700">
            Enter the API token configured for <code className="rounded bg-slate-100 px-1">{API_BASE}</code>. It is kept in this
            browser tab&apos;s session storage only and is sent as a bearer token.
          </p>
          <div>
            <label htmlFor="api-token" className="label">
              API token
            </label>
            <input
              id="api-token"
              data-autofocus
              type="password"
              autoComplete="off"
              className="input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Paste token"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => setOpen(false)}>
              Later
            </button>
            <button type="submit" className="btn-primary" disabled={!input.trim()}>
              <KeyRound size={16} aria-hidden="true" /> Connect
            </button>
          </div>
        </form>
      </Modal>
    </Ctx.Provider>
  );
}

/** Shown by pages that need a token before they can load data. */
export function ConnectGate({ children }: { children: React.ReactNode }) {
  const { token, ready, openConnect } = useAuth();
  if (!ready) return <p className="text-sm text-slate-600">Loading…</p>;
  if (!token) {
    return (
      <div className="card max-w-xl">
        <h2 className="text-lg font-semibold">Not connected</h2>
        <p className="mt-1 text-sm text-slate-700">Enter your API token to load data from the EvalForge backend.</p>
        <button type="button" className="btn-primary mt-3" onClick={openConnect}>
          <KeyRound size={16} aria-hidden="true" /> Connect
        </button>
      </div>
    );
  }
  return <>{children}</>;
}
