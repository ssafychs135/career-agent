export const VERSION = 1;
export const MAX_LINE = 65_536;
export const MAX_TOTAL = 262_144;
export const MAX_TEXT = 32_768;
export const CODES = ['disabled', 'auth_unknown', 'auth_required', 'subscription_limit', 'protocol_error', 'internal'] as const;
export type Code = typeof CODES[number];
export type Request = { v: 1; id: string; task: 'summary' | 'research'; model: 'haiku' | 'sonnet' | 'opus'; prompt: string };
export type Frame = { v: 1; id: string; type: 'step'; label: 'working' | 'web_search' | 'web_fetch' }
  | { v: 1; id: string; type: 'result'; text: string }
  | { v: 1; id: string; type: 'interrupted'; code: Code };
export function exact(value: unknown, keys: string[]): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join(',') === [...keys].sort().join(',');
}
export function request(value: unknown): Request {
  if (!exact(value, ['v', 'id', 'task', 'model', 'prompt']) || value.v !== 1
    || typeof value.id !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$(?![\s\S])/.test(value.id)
    || (typeof value.task !== 'string' || !['summary', 'research'].includes(value.task))
    || (typeof value.model !== 'string' || !['haiku', 'sonnet', 'opus'].includes(value.model))
    || typeof value.prompt !== 'string' || /[\uD800-\uDFFF]/u.test(value.prompt) || Buffer.byteLength(value.prompt) > MAX_TEXT) throw Error('protocol_error');
  return value as Request;
}
export function encode(frame: Frame): string {
  const line = JSON.stringify(frame) + '\n';
  if (Buffer.byteLength(line) > MAX_LINE) throw Error('protocol_error');
  return line;
}

// The wire request is a flat object of scalar values. Scan before JSON.parse to
// reject duplicate keys rather than silently accepting a last-wins auth override.
export function parseRequest(line: string): Request {
  if (Buffer.byteLength(line) > MAX_LINE) throw Error('protocol_error');
  let pos = /^\s*\{/.exec(line)?.[0].length;
  if (pos === undefined) throw Error('protocol_error');
  const field = /\s*("(?:[^"\\\u0000-\u001f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*")\s*:\s*("(?:[^"\\\u0000-\u001f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"|1)\s*([,}])/y;
  const keys = new Set<string>();
  while (true) {
    field.lastIndex = pos;
    const match = field.exec(line);
    if (!match) throw Error('protocol_error');
    const key = JSON.parse(match[1]!);
    if (keys.has(key)) throw Error('protocol_error');
    keys.add(key);
    pos = field.lastIndex;
    if (match[3] === '}') break;
  }
  if (line.slice(pos).trim()) throw Error('protocol_error');
  return request(JSON.parse(line));
}
