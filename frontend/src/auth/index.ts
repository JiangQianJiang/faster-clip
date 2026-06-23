/**
 * Authentication utilities for access token management.
 *
 * Access token is stored in sessionStorage (cleared when tab closes).
 * Provider API keys are configured on the server and are never stored here.
 */

const TOKEN_KEY = "live_clipper_access_token";

export function getAccessToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setAccessToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export function hasAccessToken(): boolean {
  return !!sessionStorage.getItem(TOKEN_KEY);
}

/**
 * Verify the token with the backend.
 * Returns true if the token is valid.
 */
export async function verifyToken(token: string): Promise<boolean> {
  try {
    const res = await fetch("/api/auth/verify", {
      headers: { Authorization: `Bearer ${token}` },
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Fetch wrapper that automatically attaches the Bearer token
 * and handles 401 responses by clearing the token.
 */
export async function authFetch(
  url: string,
  options: RequestInit = {},
): Promise<Response> {
  const token = getAccessToken();
  const headers = new Headers(options.headers);

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(url, { ...options, headers });

  // On 401, clear the token so the auth gate re-appears
  if (res.status === 401) {
    clearAccessToken();
    // Dispatch a custom event so the auth gate can react
    window.dispatchEvent(new CustomEvent("auth:unauthorized"));
  }

  return res;
}

/**
 * Fetch a protected resource and return it as a Blob URL.
 * Used for video, thumbnails, and downloads that need
 * to be rendered in <video>, <img>, or <a> elements which cannot
 * set custom Authorization headers.
 */
export async function authBlobUrl(url: string): Promise<string> {
  const res = await authFetch(url);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `请求失败 (${res.status})`);
  }
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

/**
 * Revoke a Blob URL to free memory.
 */
export function revokeBlobUrl(blobUrl: string): void {
  URL.revokeObjectURL(blobUrl);
}
