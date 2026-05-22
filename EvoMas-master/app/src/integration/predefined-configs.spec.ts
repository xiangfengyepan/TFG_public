/**
 * Matrix integration spec: every predefined config × every listed
 * instance runs through inference + evaluation, asserts
 * `report.resolved === true`. Adding a new config under
 * `evomas/config/predefined/` lights up coverage automatically.
 *
 * Requires:
 *   - FastAPI server on EVOMAS_API_URL (default localhost:8000/api)
 *   - Ollama reachable + each config's model pulled
 *   - Every INSTANCES id present in `swebench_instances.jsonl`
 *
 * Opt-in: `EVOMAS_RUN_INTEGRATION=1 npx vitest run app/src/integration/`.
 */
import { fileURLToPath } from 'node:url';
import { readdirSync } from 'node:fs';
import { dirname, resolve, basename } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';
import { Agent } from 'undici';

const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
const RUN = env['EVOMAS_RUN_INTEGRATION'] === '1';
const API = env['EVOMAS_API_URL'] ?? 'http://localhost:8000/api';

const SPEC_DIR = dirname(fileURLToPath(import.meta.url));
const PREDEFINED_DIR = resolve(SPEC_DIR, '../../../evomas/config/predefined');
const CONFIGS: string[] = readdirSync(PREDEFINED_DIR)
  .filter(f => f.endsWith('.json'))
  .map(f => basename(f, '.json'))
  .sort();

interface Instance { id: string; hint?: string }

/** Each entry runs inference + evaluation against every predefined config.
 * SWE-bench rows go through the harness; subset=custom rows route to
 * `apply_and_test.py` (clone → apply patch → pytest). Both write a
 * `report.json` with a `resolved` flag we assert on. */
const INSTANCES: Instance[] = [
  { id: 'custom-xiangfengyepan-evomas-test-instance-fcf59bc', hint: 'calculator.py' },
];

/** 30-min per-cell cap: long enough for slow CPU-only inference, short
 * enough that a stuck Ollama can't hang the suite indefinitely. */
const TEST_TIMEOUT_MS = 30 * 60 * 1000;

/** Disable undici's body/headers timeouts; SSE streams idle for minutes
 * while Ollama generates the next agent's response. */
const SSE_AGENT = new Agent({ bodyTimeout: 0, headersTimeout: 0 });

interface SSEEvent { type: string; [k: string]: unknown }

async function streamSSE(url: string, body: unknown): Promise<SSEEvent[]> {
  const events: SSEEvent[] = [];
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    dispatcher: SSE_AGENT,
  } as RequestInit);
  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => '');
    throw new Error(`POST ${url} -> ${res.status} ${res.statusText}: ${detail}`);
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

/** Inference + evaluation for one (config, instance) pair. Asserts
 * `report.resolved === true`. Works for both SWE-bench rows (harness)
 * and subset=custom rows (apply_and_test). */
async function runInferenceWithEval(config: string, instance: string, hint?: string): Promise<void> {
  const inferEvents = await streamSSE(`${API}/inference/run`, {
    instance_ids: [instance],
    config,
  });

  const errorEvent = inferEvents.find(e => e.type === 'error');
  expect(
    errorEvent,
    `[${config} × ${instance}] inference errored: ${(errorEvent?.['message'] as string) ?? ''}`,
  ).toBeUndefined();

  const inferenceDone = inferEvents.find(e => e.type === 'done');
  expect(inferenceDone, `[${config} × ${instance}] inference must reach 'done'`).toBeTruthy();
  const outputPath = inferenceDone?.['output_path'] as string | undefined;
  expect(outputPath, `[${config} × ${instance}] 'done' must carry output_path`).toBeTruthy();

  // Surface the patch in failure messages so a non-resolved run is
  // easy to triage without digging through server logs.
  const instanceDone = inferEvents.find(
    e => e.type === 'instance_done' && e['instance_id'] === instance,
  );
  const inferredPatch = (instanceDone?.['patch'] as string | undefined) ?? '';
  if (hint && inferredPatch && !inferredPatch.includes(hint)) {
    // eslint-disable-next-line no-console
    console.warn(`[${config} × ${instance}] patch did not mention ${hint}`);
  }

  const evalEvents = await streamSSE(`${API}/evaluation/run`, {
    predictions_path: outputPath,
    max_workers: 1,
  });

  const evalError = evalEvents.find(e => e.type === 'error');
  expect(
    evalError,
    `[${config} × ${instance}] evaluation errored: ${(evalError?.['message'] as string) ?? ''}`,
  ).toBeUndefined();

  const evalDone = evalEvents.find(e => e.type === 'done');
  expect(evalDone, `[${config} × ${instance}] evaluation must reach 'done'`).toBeTruthy();
  expect(
    evalDone?.['returncode'],
    `[${config} × ${instance}] evaluation harness exited non-zero`,
  ).toBe(0);

  const instancesRes = await fetch(`${API}/results/instances`);
  expect(instancesRes.ok, `[${config} × ${instance}] /api/results/instances 2xx`).toBe(true);
  const instances = await instancesRes.json() as Array<{
    instance_id: string;
    runs: Array<{ run_id: string; evaluation: { dir: string } | null; mtime: number }>;
  }>;
  const entry = instances.find(i => i.instance_id === instance);
  expect(entry, `[${config} × ${instance}] missing from /api/results/instances`).toBeTruthy();

  // Newest `<config>-`-prefixed run so we don't read a stale evaluation.
  const matchedRun = (entry?.runs ?? [])
    .filter(r => r.run_id.startsWith(`${config}-`) && r.evaluation)
    .sort((a, b) => b.mtime - a.mtime)[0];
  expect(
    matchedRun?.evaluation?.dir,
    `[${config} × ${instance}] no '${config}-' run with an evaluation dir`,
  ).toBeTruthy();

  const evalRes = await fetch(
    `${API}/results/evaluation?dir=${encodeURIComponent(matchedRun!.evaluation!.dir)}`,
  );
  expect(evalRes.ok, `[${config} × ${instance}] /api/results/evaluation 2xx`).toBe(true);
  const evaluation = await evalRes.json() as {
    report: Record<string, { resolved?: boolean }>;
  };
  const report = evaluation.report?.[instance];
  expect(report, `[${config} × ${instance}] report.json missing entry for ${instance}`).toBeTruthy();
  expect(
    report?.resolved,
    `[${config} × ${instance}] not resolved: report=${JSON.stringify(report)} patch:\n${inferredPatch}`,
  ).toBe(true);
}

describe.skipIf(!RUN)('integration · predefined configs', () => {
  // Fail-fast if the FastAPI server isn't reachable, so an unstarted
  // server doesn't burn the full per-cell timeout.
  beforeAll(async () => {
    try {
      const res = await fetch(`${API}/health`, {
        signal: AbortSignal.timeout(3000),
      });
      if (!res.ok) throw new Error(`API health check returned ${res.status} ${res.statusText}`);
    } catch (err) {
      throw new Error(
        `Integration matrix requires the FastAPI server on ${API}. `
        + `Start it with \`evomas api\` and re-run. Original error: ${(err as Error).message}`,
      );
    }
  });

  for (const config of CONFIGS) {
    describe(config, () => {
      for (const inst of INSTANCES) {
        it(
          `resolves ${inst.id} (inference + evaluation)`,
          async () => { await runInferenceWithEval(config, inst.id, inst.hint); },
          TEST_TIMEOUT_MS,
        );
      }
    });
  }
});
