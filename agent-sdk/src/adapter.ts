import type { AccountInfo, Options, SDKMessage } from '@anthropic-ai/claude-agent-sdk';
import { type Frame, type Request, MAX_TEXT, MAX_TOTAL, request } from './protocol.js';

// No environment variable, request field, or account fixture can enable stage 1.
// Deliberately no runtime SDK import, query(), credential reader, or provider path.
export const LIVE_ENABLED = false;
export function live(_request: Request): Frame {
  return { v: 1, id: _request.id, type: 'interrupted', code: 'disabled' };
}

export function safeEnvironment(input: NodeJS.ProcessEnv): Record<string, string> {
  const home = input.HOME;
  if (!home || !home.startsWith('/') || home.includes('\0')) throw Error('auth_unknown');
  // PATH is fixed, not inherited; even NODE_OPTIONS and LD_PRELOAD are excluded.
  return { HOME: home, PATH: '/usr/bin:/bin', LANG: 'C.UTF-8' };
}

// Fixture-only policy. Not a live authentication attestation. tokenSource is an
// unconstrained string in SDK 0.3.305; no accepted value can safely be invented.
// Even plausible subscriptionType/apiKeySource/provider combinations stay unknown.
export function subscriptionSource(_account: AccountInfo): 'auth_unknown' {
  return 'auth_unknown';
}

export function restrictedOptions(task: Request['task'], env: Record<string, string>): Options {
  if (task !== 'summary' && task !== 'research') throw Error('protocol_error');
  const tools = task === 'summary' ? [] : ['WebSearch', 'WebFetch'];
  return {
    tools, allowedTools: [...tools], settingSources: [], skills: [],
    mcpServers: {}, strictMcpConfig: true, plugins: [],
    persistSession: false, env: safeEnvironment(env),
    permissionMode: 'dontAsk',
    canUseTool: async (name, input) => tools.includes(name)
      ? { behavior: 'allow', updatedInput: input }
      : { behavior: 'deny', message: 'Tool not permitted' },
  };
}

// Offline event translation only: data supplied by unit fixtures, not a Query.
// A future live implementation must prove auth BEFORE writing a user prompt.
export function translateFixture(req: Request, events: readonly SDKMessage[]): Frame[] {
  request(req);
  const output: Frame[] = [];
  let total = 0;
  let terminal = false;
  const emit = (frame: Frame) => {
    total += Buffer.byteLength(JSON.stringify(frame) + '\n');
    if (total > MAX_TOTAL) throw Error('protocol_error');
    output.push(frame);
  };
  for (const event of events) {
    if (terminal) throw Error('protocol_error');
    if (event.type === 'assistant') {
      if (event.error) {
        emit({ v: 1, id: req.id, type: 'interrupted', code: event.error === 'authentication_failed' ? 'auth_required'
          : event.error === 'rate_limit' || event.error === 'billing_error' ? 'subscription_limit' : 'internal' });
        terminal = true;
        continue;
      }
      for (const block of event.message.content) {
        if (block.type === 'tool_use') {
          if (req.task !== 'research' || !['WebSearch', 'WebFetch'].includes(block.name)) throw Error('protocol_error');
          emit({ v: 1, id: req.id, type: 'step', label: block.name === 'WebSearch' ? 'web_search' : 'web_fetch' });
        } else if (block.type === 'text') emit({ v: 1, id: req.id, type: 'step', label: 'working' });
      }
    } else if (event.type === 'result') {
      terminal = true;
      if (event.is_error || event.subtype !== 'success') emit({ v: 1, id: req.id, type: 'interrupted', code: 'internal' });
      else {
        if (Buffer.byteLength(event.result) > MAX_TEXT) throw Error('protocol_error');
        emit({ v: 1, id: req.id, type: 'result', text: event.result });
      }
    }
  }
  if (!terminal) throw Error('protocol_error');
  return output;
}
