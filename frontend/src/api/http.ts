import { getDeviceId } from "../lib/identity";

/**
 * Single choke point for ALL network requests (REST and SSE).
 * Attaches identity (X-Device-Id + cookies) so components never need to know
 * how the user is identified — the CAS swap only touches this file and
 * lib/identity.ts.
 */

export class ApiError extends Error {
  code: string;
  retryable: boolean;
  status: number;
  retryAfterSeconds?: number;

  constructor(opts: {
    code: string;
    message: string;
    retryable: boolean;
    status: number;
    retryAfterSeconds?: number;
  }) {
    super(opts.message);
    this.name = "ApiError";
    this.code = opts.code;
    this.retryable = opts.retryable;
    this.status = opts.status;
    this.retryAfterSeconds = opts.retryAfterSeconds;
  }
}

export async function toApiError(res: Response): Promise<ApiError> {
  let code = `http_${res.status}`;
  let message = res.statusText || "Request failed";
  let retryable = res.status >= 500 || res.status === 429;
  try {
    const body = (await res.json()) as {
      error?: { code?: string; message?: string; retryable?: boolean };
    };
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      retryable = body.error.retryable ?? retryable;
    }
  } catch {
    /* non-JSON error body */
  }
  const retryAfterHeader = res.headers.get("Retry-After");
  const retryAfterSeconds =
    res.status === 429 && retryAfterHeader ? Number(retryAfterHeader) || undefined : undefined;
  return new ApiError({ code, message, retryable, status: res.status, retryAfterSeconds });
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("X-Device-Id", getDeviceId());
  if (init.body != null && typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(path, { ...init, headers, credentials: "include" });
}

/** JSON convenience wrapper: throws ApiError on non-2xx, parses JSON body. */
export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
