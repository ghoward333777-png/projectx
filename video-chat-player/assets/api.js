// Thin JSON client for api.php. Every failure becomes an ApiError with a `code` the
// callers map to a recovery; nothing here throws raw fetch errors at the UI.
export class ApiError extends Error {
  constructor(message, code, status, body) {
    super(message);
    this.code = code;
    this.status = status;
    this.body = body;
  }
}

export async function api(action, params = {}, { method = 'POST', timeoutMs = 8000, base = 'api.php' } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    let response;
    if (method === 'GET') {
      const qs = new URLSearchParams({ action, ...Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null)) });
      response = await fetch(`${base}?${qs}`, { method: 'GET', cache: 'no-store', signal: controller.signal, credentials: 'same-origin' });
    } else {
      response = await fetch(`${base}?action=${encodeURIComponent(action)}`, {
        method: 'POST', cache: 'no-store', signal: controller.signal, credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, ...params }),
      });
    }
    let body = null;
    try { body = await response.json(); } catch (_err) { body = null; }
    if (!response.ok) {
      throw new ApiError(body?.error || `Server answered ${response.status}.`, body?.code || (response.status >= 500 ? 'server_error' : 'http_error'), response.status, body);
    }
    if (!body || typeof body !== 'object') throw new ApiError('The server sent something that was not JSON.', 'bad_json', response.status, null);
    return body;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err && err.name === 'AbortError') throw new ApiError('The server took too long to answer.', 'timeout', 0, null);
    throw new ApiError('No connection to the server.', 'network', 0, null);
  } finally {
    clearTimeout(timer);
  }
}
