# TS Agent SDK stage 1 — deliberately disabled

Tracking: [Issue 17](https://github.com/ssafychs135/career-agent/issues/17), full confirmed plan in comment `6305282267` (the create operation returned an empty issue body).

## Delivered boundary

`agent-sdk/` is an isolated private Node22 package with exact SDK **0.3.305**, TypeScript5.9.3 and lockfile integrity pins. SDK package metadata declares Node >=18, native optional platform package0.3.305, and `claudeCodeVersion: 2.1.305`. The installed linux-x64 package's own binary returned `2.1.305 (Claude Code)` under an empty fixture HOME and `env -i`. No existing installed `claude` is reused. See `dependency-evidence.json` for platform SHA256 and registry integrity.

The SDK is a **type-only** dependency in the stage-1 adapter. Compiled adapter/entry contain no runtime SDK import or `query()`. `live()` returns `disabled`; `run_sdk()` unconditionally raises `SDKInterrupted('disabled')`, a `ClaudeAuthError` subtype. Neither environment flags nor wire fields can enable it. There is no credential reader, auth probe, model request, provider fallback, or deployment change. `translateFixture()` is an offline translator for test-owned SDK-shaped events, **not** a working model adapter. Its options builder demonstrates narrowed SDK options but is never passed to a live Query.

Existing `run_claude`, summary/research defaults, retries, attempts, tier policy, progress/result persistence and notifications are unchanged. No existing production module imports the bridge. Consequently **existing production behavior is preserved, not newly certified secure**. The bridge must not be substituted into research/summary yet: their full interruption/parity semantics remain a later PR. The new exception alone is not proof that all existing callers preserve attempts on activation.

## Authentication evidence and limitations

Official package `sdk.d.ts` declares `AccountInfo` optional `subscriptionType`, `tokenSource?: string`, `apiKeySource?: string` and `apiProvider`. `Query.accountInfo()` exists; the implementation awaits initialization. `ApiKeySource` explicitly says `none` may mean OAuth, bearer token **or third-party provider**, and legacy `oauth` is not currently emitted. Therefore `none` plus a subscription-looking fixture is **not accepted as subscription source attestation**. `subscriptionSource()` always returns `auth_unknown`. We did not invoke accountInfo, read auth/settings files, sign in, refresh tokens or send a prompt. Fixture metadata is not a live receipt. Activation requires a documented, verified source contract, pre-prompt ordering and authorization in a separate review.

The official overview additionally says third-party developers must not offer claude.ai login/rate limits unless previously approved. Applicability/approval for the intended eventual deployment is unresolved; **this PR does not activate it and must not be represented as approval to activate**. API key fallback is not an alternative authorized by this project.

Sources inspected 2026-10-21:
- https://code.claude.com/docs/en/agent-sdk/overview (redirect from platform.claude.com; capabilities and third-party-login note)
- https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/0.3.305 (version, engines, distribution integrity, optional packages)
- https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk-linux-x64/0.3.305
- Actual integrity-verified package README, package.json, sdk.d.ts and sdk.mjs (`accountInfo`, options env default). The default SDK env copies `process.env`; stage1 does not rely on that default.

**UNVERIFIED**: real subscription origin, login refresh, credits-off behavior, actual quota/limit handling by a live SDK, production runtime/deployment. No test here proves any of these.

## Wire and process contract

One UTF-8 JSON request per process, flat exact keys `v,id,task,model,prompt`; v=1, id `[A-Za-z0-9_-]{1,64}`, task summary/research, model haiku/sonnet/opus. No options/env/auth/tools/paths may be supplied in a request. Input duplicate keys (including escaped names), invalid JSON/UTF-8, unknown keys and trailing objects reject. Request ends at stdin EOF.

Response NDJSON exact keys:
- `{v:1,id,type:'step',label:'working'|'web_search'|'web_fetch'}` (summary only permits working)
- exactly one terminal `{v:1,id,type:'result',text:string}` **or** `{v:1,id,type:'interrupted',code:...}`
- interruption codes: disabled/auth_unknown/auth_required/subscription_limit/protocol_error/internal

No events after terminal, duplicate keys, mismatched id/version, malformed lines, partial EOF, unknown fields or nonzero exit with a result are accepted. stdout is protocol-only; raw stderr is never exposed in logs/errors. Limits: line65,536 bytes (including LF), aggregate262,144 bytes, prompt/result32,768 bytes, stderr16,384 bytes. Concurrent stderr consumption prevents pipe-backpressure deadlock; overflow aborts. Process timeout covers input/output/exit. Timeout, cancellation, parse/callback failure and success all run TERM then KILL process-group cleanup and await the direct child and pipe completion. Fixtures verify a parent reaps its own grandchild. **POSIX only; a deliberately escaped process group is outside this fixture transport's containment guarantee. Non-child reaping is the OS/parent's responsibility, not falsely claimed as waitpid by the bridge.** Do not activate without deployment containment review.

The Python exchange boundary normalizes excessive JSON nesting to `protocol_error` and unexpected spawn/transport/callback/cleanup failures to `internal`. Only fixed interruption codes escape; original exception messages, causes and contexts are not chained. `CancelledError` remains cancellation, including cancellation during a failed spawn or cleanup. Returned callback awaitables (coroutines, Futures or Tasks) are awaited inside the exchange timeout and cleanup boundary; their completion/failure is observed before any result is accepted. Cancellation also cancels an awaited callback. Callbacks must return work they start: unrelated detached tasks are not owned or sanitized by the bridge. Sanitized cancellations have no original exception context/cause. This does not claim that arbitrary caller-side traceback-local capture is safe.

Environment is rebuilt from HOME only plus fixed PATH `/usr/bin:/bin` and LANG. API keys/auth tokens, provider/baseURL/cloud flags, proxy/config overrides, NODE_OPTIONS/LD_PRELOAD and settings helpers cannot be inherited through env. Options deny settings sources, skills, plugins, MCP and arbitrary tools. Summary tools=[], research only WebSearch/WebFetch; permission callback denies all else. These are fixture-tested options, **not** evidence that managed/system configuration cannot affect a future live SDK. That review remains mandatory.

## Verification lanes

Backend tests are entirely self-contained under `backend/`, using Python-owned fake subprocesses. They need no Node, npm package, root path or build. Existing Jenkins backend:/app mount remains supported. Root-only `tests/test_sdk_stage1_integration.py` explicitly requires a built agent-sdk and `SDK_TEST_NODE` absolute Node22 binary; never move it into backend tests.

From repository root:
```
cd agent-sdk
npm ci --ignore-scripts
npm run typecheck
npm test
cd ../backend
python -m pytest -q
cd ..
SDK_TEST_NODE=/absolute/path/to/node22 python -m pytest -q tests/test_sdk_stage1_integration.py tests/test_deployment_config.py
cd frontend
npm ci --ignore-scripts
npm test
npm run build
```
Use a clean non-credential install environment, inspect dependencies' lifecycle metadata before enabling scripts. No install scripts were needed for local new-package checks. CI is deliberately unchanged: existing required checks are backend-tests/frontend-tests-build/compose-config. New Node/root integration checks are **local additional gates**, not falsely claimed as remote CI. A future activation PR must separately approve packaging/CI changes. Existing frontend test-source global type errors are a baseline, separate from the passing production build and strict new Node package typecheck.

## Remaining phased plan and rollback

1. This PR: disabled adapter/fixture/protocol/bridge only; independent review then formal CA QA/owner gates. It does **not** close the whole Issue17.
2. Next: summary/research parity, interruptions that protect attempts/tier/pending, real SDK auth-source contract and pre-prompt gate, tool/system-settings enforcement. No production calls without specific authorization.
3. Separate approved PR: Node/SDK runtime packaging, actual login-mount/HOME/numericUID contract, CI gates and activation. Current Docker/compose/Jenkins/CI and both rw mounts remain untouched.
4. Authorized actual subscription/refresh/credits observations, with limitations stated and QA/owner sign-off.

Rollback stage1 by reverting this additive PR; existing adapter remains the sole production path. Future rollback must use previous adapter or feature-off while preserving pending, never API/paid-provider fallback. Do not enable by editing a boolean alone.
