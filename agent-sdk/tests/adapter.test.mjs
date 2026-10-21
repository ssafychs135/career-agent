import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { readFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { LIVE_ENABLED, live, restrictedOptions, safeEnvironment, subscriptionSource, translateFixture } from '../dist/adapter.js';
import { MAX_LINE, MAX_TEXT, encode, parseRequest, request } from '../dist/protocol.js';

const req = { v: 1, id: 'fixture_1', task: 'summary', model: 'haiku', prompt: 'fixture 한국어' };
const success = { type: 'result', subtype: 'success', is_error: false, result: 'fixture result' };
const assistant = content => ({ type: 'assistant', message: { content } });

test('live source gate cannot be enabled by auth/env/request', () => {
  assert.equal(LIVE_ENABLED, false);
  assert.deepEqual(live(req), { v: 1, id: req.id, type: 'interrupted', code: 'disabled' });
  assert(!readFileSync(new URL('../dist/adapter.js', import.meta.url), 'utf8').includes('from \'@anthropic-ai'));
});

test('all metadata combinations remain unknown: no invented tokenSource confidence', () => {
  for (const account of [{}, { apiProvider: 'firstParty', subscriptionType: 'max', apiKeySource: 'none', tokenSource: 'oauth' },
    { apiProvider: 'bedrock' }, { apiProvider: 'vertex' }, { apiProvider: 'foundry' },
    { apiKeySource: 'ANTHROPIC_API_KEY' }, { apiKeySource: 'apiKeyHelper' },
    { apiKeySource: '/login managed key' }, { tokenSource: 'claude.ai' }]) {
    assert.equal(subscriptionSource(account), 'auth_unknown');
  }
});

test('environment is an allowlist, not a blacklist', () => {
  const hostile = Object.fromEntries(['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL',
    'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY',
    'CLAUDE_CONFIG_DIR', 'NODE_OPTIONS', 'LD_PRELOAD', 'HTTPS_PROXY', 'AWS_PROFILE', 'PATH', 'apiKeyHelper', 'GOOGLE_APPLICATION_CREDENTIALS'].map(key => [key, 'fixture']));
  assert.deepEqual(safeEnvironment({ ...hostile, HOME: '/fixture/home' }), { HOME: '/fixture/home', PATH: '/usr/bin:/bin', LANG: 'C.UTF-8' });
  for (const HOME of ['', 'relative', '/bad\0home']) assert.throws(() => safeEnvironment({ HOME }));
});

test('capability reduction: no inherited settings, skills, plugins, MCP or arbitrary tools', async () => {
  for (const task of ['summary', 'research']) {
    const options = restrictedOptions(task, { HOME: '/fixture' });
    const allowed = task === 'summary' ? [] : ['WebSearch', 'WebFetch'];
    assert.deepEqual(options.tools, allowed);
    assert.deepEqual(options.allowedTools, allowed);
    assert.deepEqual(options.settingSources, []);
    assert.deepEqual(options.skills, []);
    assert.deepEqual(options.plugins, []);
    assert.deepEqual(options.mcpServers, {});
    assert.equal(options.strictMcpConfig, true);
    assert.equal(options.persistSession, false);
    for (const name of ['Bash', 'Read', 'Write', 'Agent', 'Skill', 'mcp__hostile', 'WebSearch', 'WebFetch']) {
      const response = await options.canUseTool(name, { query: 'fixture' }, {});
      assert.equal(response.behavior, allowed.includes(name) ? 'allow' : 'deny');
    }
  }
});

test('request strict flat schema and duplicate keys (including escaped names)', () => {
  assert.deepEqual(parseRequest(JSON.stringify(req) + '\n'), req);
  for (const input of [JSON.stringify({ ...req, env: { ANTHROPIC_API_KEY: 'fixture' } }),
    JSON.stringify({ ...req, tools: ['Bash'] }), JSON.stringify({ ...req, model: 'api-provider' }),
    JSON.stringify({ ...req, v: true }), JSON.stringify({ ...req, task: 'Bash' }),
    JSON.stringify({ ...req, id: 'bad id' }), JSON.stringify({ ...req, id: 'bad\n' }),
    JSON.stringify({ ...req, prompt: '\ud800' }), JSON.stringify({ ...req, prompt: 'x'.repeat(MAX_TEXT + 1) }),
    JSON.stringify(req).replace('"v":1', '"v":1,"v":1'),
    JSON.stringify(req).replace('"v":1', '"v":1,"\\u0076":1'),
    JSON.stringify(req) + JSON.stringify(req), '{', '[]', 'x'.repeat(MAX_LINE + 1)]) {
    assert.throws(() => parseRequest(input), /protocol_error/);
  }
  assert.throws(() => request(null));
  assert.throws(() => request({ ...req, task: ['summary'] }));
  assert.throws(() => request({ ...req, model: ['haiku'] }));
  assert.equal(request({ ...req, prompt: '👩‍💻' }).prompt, '👩‍💻');
  assert.throws(() => encode({ ...req, text: 'x'.repeat(MAX_LINE) }));
});

test('offline event translation, single terminal and result bounds', () => {
  assert.deepEqual(translateFixture(req, [assistant([{ type: 'text', text: 'x' }]), success]), [
    { v: 1, id: req.id, type: 'step', label: 'working' },
    { v: 1, id: req.id, type: 'result', text: 'fixture result' },
  ]);
  for (const events of [[], [success, success], [success, assistant([])],
    [{ ...success, result: 'x'.repeat(MAX_TEXT + 1) }],
    [assistant([{ type: 'tool_use', name: 'Bash', input: { command: 'fixture' } }]), success],
    [assistant([{ type: 'tool_use', name: 'WebSearch', input: {} }]), success],
    [assistant(Array.from({ length: 10000 }, () => ({ type: 'text', text: 'x' }))), success]]) {
    assert.throws(() => translateFixture(req, events), /protocol_error/);
  }
  for (const name of ['WebSearch', 'WebFetch']) {
    const frames = translateFixture({ ...req, task: 'research' }, [assistant([{ type: 'tool_use', name, input: {} }]), success]);
    assert.equal(frames[0].label, name === 'WebSearch' ? 'web_search' : 'web_fetch');
  }
});

test('auth/limit interruptions are never content or retry results', () => {
  for (const [error, code] of [['authentication_failed', 'auth_required'], ['rate_limit', 'subscription_limit'], ['billing_error', 'subscription_limit']]) {
    assert.deepEqual(translateFixture(req, [{ ...assistant([]), error }]), [{ v: 1, id: req.id, type: 'interrupted', code }]);
  }
  assert.equal(translateFixture(req, [{ ...success, is_error: true }])[0].code, 'internal');
});

test('real disabled entry: stdout protocol only, no SDK runtime, sanitized fixture HOME', () => {
  const home = mkdtempSync(join(tmpdir(), 'sdk-disabled-'));
  try {
    const entry = new URL('../dist/main.js', import.meta.url);
    const result = spawnSync(process.execPath, [entry.pathname], { input: JSON.stringify(req),
      env: { HOME: home, PATH: '/usr/bin:/bin', CAREER_AGENT_SDK_ENABLED: 'true' }, encoding: 'utf8', timeout: 2000 });
    assert.equal(result.status, 0);
    assert.equal(result.stderr, '');
    assert.deepEqual(JSON.parse(result.stdout), live(req));
    const bad = spawnSync(process.execPath, [entry.pathname], { input: 'x'.repeat(MAX_LINE + 1),
      env: { HOME: home, PATH: '/usr/bin:/bin' }, encoding: 'utf8', timeout: 2000 });
    assert.equal(bad.status, 2);
    assert.equal(bad.stdout, '');
    assert.equal(bad.stderr, '');
  } finally { rmSync(home, { recursive: true, force: true }); }
});

test('SDK and platform bundle lock match pinned official evidence', () => {
  const lock = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url), 'utf8'));
  const evidence = JSON.parse(readFileSync(new URL('../dependency-evidence.json', import.meta.url), 'utf8'));
  for (const name of ['@anthropic-ai/claude-agent-sdk', '@anthropic-ai/claude-agent-sdk-linux-x64']) {
    const pkg = lock.packages['node_modules/' + name];
    assert.equal(pkg.version, '0.3.305');
    assert.equal(pkg.integrity, evidence[name].integrity);
    assert(pkg.resolved.startsWith('https://registry.npmjs.org/'));
  }
  const sdk = JSON.parse(readFileSync(new URL('../node_modules/@anthropic-ai/claude-agent-sdk/package.json', import.meta.url), 'utf8'));
  assert.equal(sdk.claudeCodeVersion, evidence.bundledCLI.version);
  assert.equal(sdk.optionalDependencies['@anthropic-ai/claude-agent-sdk-linux-x64'], '0.3.305');
  assert.throws(() => restrictedOptions('Bash', { HOME: '/fixture' }), /protocol_error/);
});
