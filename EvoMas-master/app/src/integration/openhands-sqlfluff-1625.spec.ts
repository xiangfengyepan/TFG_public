/**
 * End-to-end integration test: the `openhands` config must resolve
 * sqlfluff__sqlfluff-1625 -- same instance the evo-star and star specs
 * use, but with the OpenHands single-agent chain (`agent_controller ->
 * codeact_agent`, OpenHands-style prompts and tools verbatim from upstream
 * plus the two deterministic helpers `detect_bug_class` /
 * `derive_description_fix`).
 *
 * Same shape as the other two integration specs:
 *   1. POST /api/inference/run   -- run the `openhands` topology and wait
 *      for the SSE `done` event (carrying the output prediction `.jsonl`).
 *   2. POST /api/evaluation/run  -- run the SWE-bench harness against the
 *      prediction file and wait for the SSE `done` event.
 *   3. GET  /api/results/instances + /api/results/evaluation -- check the
 *      report.json for the instance has `resolved: true`.
 *
 * Requirements: FastAPI on localhost:8000, Ollama up, WSL+SWE-bench venv
 * for the harness, and the instance line present in swebench_instances.jsonl.
 *
 * Opt-in via env: `EVOMAS_RUN_INTEGRATION=1 npx vitest run src/integration/`.
 * Expected wall-clock: ~5-20 minutes depending on hardware (openhands is a
 * single-agent chain so it's typically faster than star's four-agent chain).
 */

import { describe, expect, it } from 'vitest';
import { Agent } from 'undici';

// Vitest exposes the Node `process` global at runtime; use `globalThis` so
// the spec compiles under tsconfig.spec.json (which doesn't pull in
// `@types/node` and therefore doesn't know about `process`).
const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
const RUN = env['EVOMAS_RUN_INTEGRATION'] === '1';
const API = env['EVOMAS_API_URL'] ?? 'http://localhost:8000/api';
const INSTANCE = 'sqlfluff__sqlfluff-1625';
const CONFIG = 'openhands';

/** Inference can run for many minutes per instance on a local LLM; cap at
 * 45 minutes to avoid hanging CI forever if the harness deadlocks. */
const TEST_TIMEOUT_MS = 45 * 60 * 1000;

/** Disable undici's per-chunk body timeout (default ~5 min). SSE streams can
 * sit quiet for several minutes while Ollama generates the next response;
 * the default would surface as `UND_ERR_BODY_TIMEOUT` mid-run. */
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

describe.skipIf(!RUN)('integration · openhands resolves sqlfluff__sqlfluff-1625', () => {
  it('runs inference + evaluation and reports resolved=true', async () => {
    // ── 1. Inference ───────────────────────────────────────────────
    const inferEvents = await streamSSE(`${API}/inference/run`, {
      instance_ids: [INSTANCE],
      config: CONFIG,
    });

    const errorEvent = inferEvents.find(e => e.type === 'error');
    expect(
      errorEvent,
      `inference errored: ${(errorEvent?.['message'] as string) ?? ''}`,
    ).toBeUndefined();

    const inferenceDone = inferEvents.find(e => e.type === 'done');
    expect(inferenceDone, 'inference must reach a `done` SSE event').toBeTruthy();
    const outputPath = inferenceDone?.['output_path'] as string | undefined;
    expect(outputPath, 'inference `done` event must carry an output_path').toBeTruthy();

    // ── 2. Evaluation ──────────────────────────────────────────────
    const evalEvents = await streamSSE(`${API}/evaluation/run`, {
      predictions_path: outputPath,
      max_workers: 1,
    });

    const evalError = evalEvents.find(e => e.type === 'error');
    expect(
      evalError,
      `evaluation errored: ${(evalError?.['message'] as string) ?? ''}`,
    ).toBeUndefined();

    const evalDone = evalEvents.find(e => e.type === 'done');
    expect(evalDone, 'evaluation must reach a `done` SSE event').toBeTruthy();
    expect(
      evalDone?.['returncode'],
      'evaluation harness exited non-zero',
    ).toBe(0);

    // ── 3. Verify resolved=true via the Results endpoints ──────────
    const instancesRes = await fetch(`${API}/results/instances`);
    expect(instancesRes.ok, '/api/results/instances should respond 2xx').toBe(true);
    const instances = await instancesRes.json() as Array<{
      instance_id: string;
      runs: Array<{ run_id: string; evaluation: { dir: string } | null; mtime: number }>;
    }>;
    const entry = instances.find(i => i.instance_id === INSTANCE);
    expect(entry, `${INSTANCE} missing from /api/results/instances`).toBeTruthy();

    // Pick the NEWEST `openhands-` run by mtime so iteration N's
    // assertion doesn't read iteration N-1's stale evaluation.
    const openhandsRun = (entry?.runs ?? [])
      .filter(r => r.run_id.startsWith('openhands-') && r.evaluation)
      .sort((a, b) => b.mtime - a.mtime)[0];
    expect(openhandsRun?.evaluation?.dir, 'no openhands-prefixed run with an evaluation dir').toBeTruthy();

    const evalRes = await fetch(
      `${API}/results/evaluation?dir=${encodeURIComponent(openhandsRun!.evaluation!.dir)}`,
    );
    expect(evalRes.ok, '/api/results/evaluation should respond 2xx').toBe(true);
    const evaluation = await evalRes.json() as {
      report: Record<string, { resolved?: boolean }>;
    };
    const report = evaluation.report?.[INSTANCE];
    expect(report, `report.json missing entry for ${INSTANCE}`).toBeTruthy();
    expect(
      report?.resolved,
      `${INSTANCE} not resolved by openhands: report=${JSON.stringify(report)}`,
    ).toBe(true);
  }, TEST_TIMEOUT_MS);
});
