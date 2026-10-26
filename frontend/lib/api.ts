"use client";

/** Thin fetch wrapper: attaches the JWT from localStorage, throws on non-2xx
 * with the server's error detail. localStorage is a deliberate dev-only
 * choice — see docs/SECURITY.md's frontend note for why this becomes an
 * httpOnly cookie in a hardened deployment (Phase 10), not before.
 */

const TOKEN_KEY = "netsphere_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`/api/v1${path}`, { ...options, headers });
  if (!res.ok) {
    let detail: unknown = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail ?? body;
    } catch {
      /* ignore body parse failure */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

async function _formRequest<T>(path: string, method: "POST" | "PUT", form: FormData): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`/api/v1${path}`, { method, headers, body: form });
  if (!res.ok) {
    let detail: unknown = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail ?? body;
    } catch {
      /* ignore body parse failure */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  delete: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
  /** multipart/form-data POST/PUT (file uploads) — no Content-Type header, so
   * the browser sets it itself with the multipart boundary. */
  postForm: async <T,>(path: string, form: FormData): Promise<T> => _formRequest<T>(path, "POST", form),
  putForm: async <T,>(path: string, form: FormData): Promise<T> => _formRequest<T>(path, "PUT", form),
  /** GET that returns a Blob with the auth header attached, then triggers
   * a browser download — used for CSV export (a plain <a href> can't send
   * the bearer token). */
  downloadFile: async (path: string, filename: string): Promise<void> => {
    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`/api/v1${path}`, { headers });
    if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};

export async function login(email: string, password: string): Promise<string> {
  const res = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? "login failed");
  }
  const data = await res.json();
  setToken(data.access_token);
  return data.access_token as string;
}
