/** Typed API error class and helper for consistent error handling across all API clients. */

/**
 * Thrown by {@link handleFetchError} whenever a fetch response is not OK (status >= 400).
 * Carries the HTTP status code and, when the server sends a FastAPI-style error body,
 * the `detail` field from that body.
 */
export class ApiError extends Error {
  readonly statusCode: number;
  readonly detail: string | undefined;

  constructor(statusCode: number, message: string, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.statusCode = statusCode;
    this.detail = detail;
  }
}

/**
 * Call this after a `fetch()` call when `res.ok` is `false`.
 * Attempts to parse the FastAPI error body for a `detail` field (which may be a
 * string or a Pydantic validation error array), then throws an {@link ApiError}.
 *
 * The return type is `Promise<never>` so TypeScript knows this always throws.
 *
 * @example
 * const res = await fetch("/api/foo");
 * if (!res.ok) await handleFetchError(res);
 */
export async function handleFetchError(res: Response): Promise<never> {
  let detail: string | undefined;

  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body.detail)) {
      // Pydantic validation errors: array of {msg, loc, type, ...}
      detail = (body.detail as Array<{ msg?: string }>)
        .map(e => e.msg ?? String(e))
        .join(" · ");
    }
  } catch {
    // Body is not JSON or is empty — leave detail undefined.
  }

  const message = detail ?? `Request failed (${res.status})`;
  throw new ApiError(res.status, message, detail);
}
