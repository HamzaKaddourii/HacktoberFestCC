export async function api<T>(url: string, body?: unknown, method?: string): Promise<T> {
  const init: RequestInit = body === undefined && !method ? {} : {
    method: method ?? 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
  const res = await fetch('/api' + url, init);
  const data = await res.json();
  if (!res.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : 'Please check the request and try again.';
    throw new Error(detail);
  }
  return data;
}

export const km = (m: number) => (m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`);
