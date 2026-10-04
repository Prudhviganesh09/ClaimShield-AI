export class ApiError extends Error {
  constructor(message: string, public status: number) {super(message);}
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {...options, headers, credentials: "same-origin", cache: "no-store",
      signal: options.signal || AbortSignal.timeout(600000)});
  } catch (error) {
    if (error instanceof Error && ["TimeoutError", "AbortError"].includes(error.name)) {
      throw new ApiError("The request timed out. Your saved claim and documents remain available. " +
        "Refresh the claim to check whether processing finished.", 0);
    }
    throw new ApiError("The server could not be reached. Check your connection and retry.", 0);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof data.detail === "string" ? data.detail : Array.isArray(data.detail)
      ? data.detail.map((d: {msg: string}) => d.msg).join(". ") : "The request could not be completed.";
    throw new ApiError(message, response.status);
  }
  return data;
}
