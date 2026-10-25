import { token } from "./auth";
export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public requestId?: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    agency?: string;
    signal?: AbortSignal;
  } = {},
): Promise<{ data: T; meta: Record<string, unknown> }> {
  const accessToken = await token();
  if (!accessToken)
    throw new ApiError("Please sign in to continue", "UNAUTHORIZED");
  const response = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1${path}`,
    {
      method: options.method || "GET",
      signal: options.signal,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...(options.agency ? { "X-Agency-ID": options.agency } : {}),
        ...(options.body ? { "Content-Type": "application/json" } : {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      cache: "no-store",
    },
  );
  const result = await response.json();
  if (!response.ok) {
    const details = result.error?.details
      ?.map(
        (item: { field: string; message: string }) =>
          `${item.field}: ${item.message}`,
      )
      .join("; ");
    throw new ApiError(
      details || result.error?.message || "Request failed",
      result.error?.code || "REQUEST_FAILED",
      result.error?.request_id,
    );
  }
  return result;
}

export async function allRecords<T>(
  path: string,
  agency: string,
): Promise<{ data: T[] }> {
  const data: T[] = [];
  for (let offset = 0; ; offset += 100) {
    const result = await api<T[]>(
      `${path}${path.includes("?") ? "&" : "?"}limit=100&offset=${offset}`,
      { agency },
    );
    data.push(...result.data);
    if (result.data.length < 100) return { data };
  }
}
