import { afterEach, describe, expect, it, vi } from 'vitest';
import { authHeader, clearToken, getToken, setToken, subscribeToken } from './auth';

describe('authentication token helpers', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('stores tokens in session storage and notifies subscribers', () => {
    const values = new Map<string, string>();
    const sessionStorage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    };
    vi.stubGlobal('window', { sessionStorage });
    const listener = vi.fn();
    const unsubscribe = subscribeToken(listener);

    setToken('example-token');
    expect(getToken()).toBe('example-token');
    expect(listener).toHaveBeenCalledOnce();

    unsubscribe();
    clearToken();
    expect(getToken()).toBeNull();
    expect(listener).toHaveBeenCalledOnce();
  });

  it('adds a bearer header only when a token exists', () => {
    expect(authHeader('example-token')).toEqual({ Authorization: 'Bearer '.concat('example-token') });
    expect(authHeader(null)).toEqual({});
  });
});
