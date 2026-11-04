// Optional QueryBook cloud (spec §0, §11). Never on the critical path: the
// on-device result is always computed and shown first. The router only calls
// out when the user is online AND opted in AND a gateway is configured AND the
// local result would benefit (low coverage or long input). Any cloud answer
// without coverage and per-word provenance is rejected, so the trust layer
// behaves identically online and off.

export const ROUTE = { LOCAL: 'local', CLOUD: 'cloud' };

export function isOnline() {
  return typeof navigator === 'undefined' ? false : navigator.onLine !== false;
}

/** Per-stage local-vs-cloud plan (the client-side twin of POST /model-selection). */
export function plan(settings, { coverage = 100, words = 0, online = isOnline() } = {}) {
  const eligible = online && settings.cloudOptIn && !!settings.gatewayUrl && !settings.forceOffline;
  const reasons = [];
  if (settings.forceOffline) reasons.push('forced offline');
  else if (!online) reasons.push('no network');
  else if (!settings.cloudOptIn) reasons.push('cloud not opted in');
  else if (!settings.gatewayUrl) reasons.push('no gateway configured');
  const benefit = coverage < settings.cloudBelowCoverage || words > 18;
  const mt = eligible && (settings.forceCloud || benefit) ? ROUTE.CLOUD : ROUTE.LOCAL;
  if (eligible && mt === ROUTE.LOCAL) reasons.push('on-device result is good enough');
  return { normalize: ROUTE.LOCAL, lid: ROUTE.LOCAL, mt, pronounce: ROUTE.LOCAL, tts: ROUTE.LOCAL, reasons };
}

/** Validate that a cloud MT response honours the covenant. */
export function validateCloudResult(r) {
  if (!r || typeof r.output !== 'string') return 'missing output';
  if (!r.coverage || typeof r.coverage.percent !== 'number') return 'missing coverage';
  if (!Array.isArray(r.segments) || r.segments.length === 0) return 'missing per-word provenance';
  for (const s of r.segments) {
    if (typeof s.source !== 'string' || typeof s.target !== 'string') return 'malformed segment';
    if (!s.flagged && !(s.provenance && (s.provenance.source || s.provenance.engine))) return 'segment without provenance';
  }
  return null;
}

/**
 * POST /mt to the configured gateway. Resolves to a result object or null
 * (unavailable, slow, malformed) — the caller keeps the on-device result.
 */
export async function cloudTranslate(settings, req, { timeoutMs = 1500, fetchImpl = (...a) => fetch(...a) } = {}) {
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = ctl ? setTimeout(() => ctl.abort(), timeoutMs) : null;
  try {
    const res = await fetchImpl(settings.gatewayUrl.replace(/\/$/, '') + '/mt', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: req.text, src: req.src, srcDialect: req.srcDialect, tgt: req.tgt, tgtDialect: req.tgtDialect, domain: req.domain }),
      signal: ctl ? ctl.signal : undefined,
    });
    if (!res.ok) return { error: `gateway returned ${res.status}` };
    const body = await res.json();
    const problem = validateCloudResult(body);
    if (problem) return { error: `rejected cloud result: ${problem}` };
    return { result: { ...body, engine: 'cloud', segments: body.segments.map((s) => ({ ...s, provenance: { type: 'cloud', ...(s.provenance || {}) } })) } };
  } catch (e) {
    return { error: e.name === 'AbortError' ? 'cloud too slow — kept on-device result' : 'cloud unreachable — kept on-device result' };
  } finally {
    if (timer) clearTimeout(timer);
  }
}
