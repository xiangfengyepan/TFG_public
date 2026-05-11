/**
 * Inference-only integration tests for the type-driven configs.
 *
 * Sibling to evo-star-sqlfluff-1625.spec.ts, but stops at the prediction
 * stage — no SWE-bench harness call. The point is to confirm that the
 * `openhands` and `star` topologies actually run end-to-end through
 * /api/inference/run and emit a non-empty `model_patch` for the same
 * instance evo-star is verified against (sqlfluff__sqlfluff-1625).
 *
 * Per config the test:
 *   1. POSTs /api/inference/run with { config, instance_ids }.
 *   2. Walks the SSE stream until the `done` event arrives.
 *   3. Expects no `error` event and an `instance_done` event whose
 *      `patch` field is a non-empty string. Falls back to reading the
 *      written `output_path` JSONL line if `instance_done.patch` is
 *      missing (older worker versions didn't include it).
 *
 * Requirements: same as evo-star-sqlfluff-1625.spec.ts (FastAPI on
 * localhost:8000, Ollama reachable, instance line in
 * `swebench_instances.jsonl`). No WSL / SWE-bench harness needed
 * since these tests skip the evaluation step.
 *
 * Opt-in via env: `EVOMAS_RUN_INTEGRATION=1 npx ng test`. Each config
 * typically takes 5–15 minutes on a local LLM.
 */

import { describe, expect, it } from 'vitest';
import { Agent } from 'undici';

const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
const RUN = env['EVOMAS_RUN_INTEGRATION'] === '1';
const API = env['EVOMAS_API_URL'] ?? 'http://localhost:8000/api';
const INSTANCE = 'sqlfluff__sqlfluff-1625';

/** Local-LLM inference can run for many minutes per instance; cap at
 * 30 min so a hung job doesn't block the suite forever. */
const TEST_TIMEOUT_MS = 30 * 60 * 1000;

/** Disable undici's per-chunk body timeout (default ~5 min). SSE streams can
 * sit quiet for several minutes while Ollama generates the next agent's
 * response; the default would surface as `UND_ERR_BODY_TIMEOUT` mid-run. */
const SSE_AGENT = new Agent({ bodyTimeout: 0, headersTimeout: 0 });

interface SSEEvent { type: string; [k: string]: unknown }

/** POST `body` to `url` and consume the SSE response stream until it ends.
 * Each `data: {...}` line becomes a parsed event in the returned array. */
async function streamSSE(url: string, body: unknown): Promise<SSEEvent[]> {
  const events: SSEEvent[] = [];
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    // `dispatcher` is a Node-fetch extension exposed by undici; not in the
    // standard RequestInit type, so cast around it.
    dispatcher: SSE_AGENT,
  } as RequestInit);
  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => '');
    throw new Error(`POST ${url} → ${res.status} ${res.statusText}: ${detail}`);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() ?? '';
    for (const raw of lines) {
      const line = raw.trim();
      if (!line.startsWith('data: ')) continue;
      try { events.push(JSON.parse(line.slice(6)) as SSEEvent); } catch { /* skip */ }
    }
  }
  return events;
}

/** Drive one inference run for `config` against `INSTANCE` and assert
 * the run produced a non-empty model_patch. Used as the body of each
 * per-config `it()` so the two configs are reported as independent
 * test cases (one can fail without short-circuiting the other). */
async function runInferenceAndExpectPatch(config: string): Promise<void> {
  const events = await streamSSE(`${API}/inference/run`, {
    config,
    instance_ids: [INSTANCE],
  });

  const errorEvent = events.find(e => e.type === 'error');
  expect(
    errorEvent,
    `[${config}] inference errored: ${(errorEvent?.['message'] as string) ?? ''}`,
  ).toBeUndefined();

  const inferenceDone = events.find(e => e.type === 'done');
  expect(inferenceDone, `[${config}] inference must reach a 'done' SSE event`).toBeTruthy();

  // Preferred path: `instance_done` events carry the per-instance final
  // patch directly so the spec doesn't have to round-trip the JSONL.
  const instanceDone = events.find(
    e => e.type === 'instance_done' && e['instance_id'] === INSTANCE,
  );
  expect(instanceDone, `[${config}] no instance_done event for ${INSTANCE}`).toBeTruthy();

  const inlinePatch = instanceDone?.['patch'];
  if (typeof inlinePatch === 'string' && inlinePatch.trim().length > 0) {
    return; // good — non-empty patch on the wire
  }

  // Fallback: older workers may not include `patch` on instance_done.
  // Read the prediction file and check `model_patch`.
  const outputPath = inferenceDone?.['output_path'] as string | undefined;
  expect(outputPath, `[${config}] 'done' event must carry an output_path`).toBeTruthy();

  const predRes = await fetch(
    `${API}/results/prediction?path=${encodeURIComponent(outputPath!)}&instance_id=${encodeURIComponent(INSTANCE)}`,
  );
  expect(predRes.ok, `[${config}] /api/results/prediction should respond 2xx`).toBe(true);
  const pred = await predRes.json() as { data?: { model_patch?: string } };
  const modelPatch = pred.data?.model_patch ?? '';
  expect(
    modelPatch.trim().length,
    `[${config}] prediction's model_patch is empty`,
  ).toBeGreaterThan(0);
}

describe.skipIf(!RUN)('integration · inference-only', () => {
  it(
    'openhands produces a non-empty model_patch for sqlfluff__sqlfluff-1625',
    async () => { await runInferenceAndExpectPatch('openhands'); },
    TEST_TIMEOUT_MS,
  );

  it(
    'star produces a non-empty model_patch for sqlfluff__sqlfluff-1625',
    async () => { await runInferenceAndExpectPatch('star'); },
    TEST_TIMEOUT_MS,
  );
});
