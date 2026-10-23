const TOKEN_KEY = 'evalforge_api_token';
const tokenListeners = new Set<() => void>();

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return window.sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === 'undefined') return;
  window.sessionStorage.setItem(TOKEN_KEY, token);
  tokenListeners.forEach((listener) => listener());
}

export function clearToken(): void {
  if (typeof window === 'undefined') return;
  window.sessionStorage.removeItem(TOKEN_KEY);
  tokenListeners.forEach((listener) => listener());
}

export function subscribeToken(listener: () => void): () => void {
  tokenListeners.add(listener);
  return () => tokenListeners.delete(listener);
}

export function authHeader(token: string | null): Record<string, string> {
  return token ? { Authorization: 'Bearer '.concat(token) } : {};
}
