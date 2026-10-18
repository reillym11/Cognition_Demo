import createClient from "openapi-fetch";
import type { paths } from "./schema";

function csrf(): string {
  const m = document.cookie.match(/(?:^|; )itp_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export const api = createClient<paths>({ baseUrl: "" });
api.use({
  onRequest({ request }) {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) request.headers.set("X-CSRF-Token", csrf());
    return request;
  },
});

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

/** Untyped JSON helper for tool pages; server enforces everything, the UI only displays. */
export async function http<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (!["GET", "HEAD"].includes(method)) headers["X-CSRF-Token"] = csrf();
  const r = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin" });
  if (!r.ok) {
    let msg = r.statusText;
    let code: string | undefined;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
      code = j.code;
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(r.status, msg, code);
  }
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}
