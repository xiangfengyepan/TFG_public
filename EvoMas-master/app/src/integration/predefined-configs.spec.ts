/**
 * Matrix-driven integration spec for every predefined config under
 * `evomas/config/predefined/`. Replaces the earlier per-config specs
 * (chain-sqlfluff-1625.spec.ts + custom-evomas-test-instance.spec.ts);
 * adding a new predefined config now lights up coverage automatically
 * — no spec edits required.
 *
 * Two hardcoded instance lists distinguish the assertion shape per cell:
 *
 *   EVAL_INSTANCES  — real SWE-bench rows. Drives inference + the
 *                     SWE-bench harness, asserts `report.resolved === true`.
 *   INFERENCE_ONLY  — `subset="custom"` rows the harness can't score.
 *                     Drives inference only, asserts a non-empty
 *                     `model_patch` came back.
 *
 * Requirements:
 *   - FastAPI server on localhost:8000.
 *   - Ollama reachable + the model each config references is pulled.
 *   - Every instance id below present in `swebench_instances.jsonl`. The
 *     custom row can be added once via the Inference page's `+ Custom`
 *     modal pointing at `xiangfengyepan/evomas-test-instance`.
 *
 * Opt-in: `EVOMAS_RUN_INTEGRATION=1 npx vitest run app/src/integration/`.
 * Wall-clock per cell: 3-30 min on a local LLM.
 */
import { fileURLToPath } from 'node:url';
import { readdirSync } from 'node:fs';
import { dirname, resolve, basename } from 'node:path';
import { describe, expect, it } from 'vitest';
import { Agent } from 'undici';

const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
const RUN = env['EVOMAS_RUN_INTEGRATION'] === '1';
const API = env['EVOMAS_API_URL'] ?? 'http://localhost:8000/api';

// Spec file is at app/src/integration/; predefined configs live at
// repo-root/evomas/config/predefined. Resolve via the file URL so the
// path works whether vitest is invoked from `app/` or repo root.
const SPEC_DIR = dirname(fileURLToPath(import.meta.url));
const PREDEFINED_DIR = resolve(SPEC_DIR, '../../../evomas/config/predefined');
const CONFIGS: string[] = readdirSync(PREDEFINED_DIR)
  .filter(f => f.endsWith('.json'))
  .map(f => basename(f, '.json'))
  .sort();

// ─── Hardcoded instance lists ─────────────────────────────────────────
interface EvalInstance { id: string; }
interface InferenceOnlyInstance { id: string; hint?: string; }

const EVAL_INSTANCES: EvalInstance[] = [
  { id: 'sqlfluff__sqlfluff-1625' },
];

/** Custom GitHub-repo rows can't be scored by the SWE-bench harness
 * (they lack `test_patch` / `FAIL_TO_PASS` / `PASS_TO_PASS`), so the
 * assertion stops at inference. `hint` is the buggy file we expect to
 * see in the patch — surfaced in the failure message when missing,
 * not asserted (different topologies may pick adjacent paths). */
const INFERENCE_ONLY_INSTANCES: InferenceOnlyInstance[] = [
  { id: 'custom-xiangfengyepan-evomas-test-instance-fcf59bc', hint: 'calculator.py' },
];

/** Cap each cell at 45 min — long enough for slow CPU-only inference,
 * short enough that a stuck Ollama doesn't hang CI forever. */
const TEST_TIMEOUT_MS = 45 * 60 * 1000;

/** Disable undici's per-chunk body timeout (default ~5 min). SSE
 * streams sit quiet for several minutes while Ollama generates the
 * next agent's response; otherwise we'd get `UND_ERR_BODY_TIMEOUT`. */
const SSE_AGENT = new Agent({ bodyTimeout: 0, headersTimeout: 0 });

interface SSEEvent { type: string; [k: string]: unknown }

/** POST `body` to `url` and consume the SSE response stream until it
 * ends. Each `data: {...}` line becomes a parsed event in the array. */
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

// ─── Assertion helpers (one per instance kind) ────────────────────────

/** Drive inference + the SWE-bench harness for a (config, instance)
 * pair and assert `report.resolved === true`. Mirrors the body of the
 * old chain-sqlfluff-1625 spec, parameterised by config + instance. */
async function runInferenceWithEval(config: string, instance: string): Promise<void> {
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
  expect(inferenceDone, `[${config} × ${instance}] inference must reach a 'done' SSE event`).toBeTruthy();
  const outputPath = inferenceDone?.['output_path'] as string | undefined;
  expect(outputPath, `[${config} × ${instance}] 'done' event must carry an output_path`).toBeTruthy();

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
  expect(evalDone, `[${config} × ${instance}] evaluation must reach a 'done' SSE event`).toBeTruthy();
  expect(
    evalDone?.['returncode'],
    `[${config} × ${instance}] evaluation harness exited non-zero`,
  ).toBe(0);

  const instancesRes = await fetch(`${API}/results/instances`);
  expect(instancesRes.ok, `[${config} × ${instance}] /api/results/instances should respond 2xx`).toBe(true);
  const instances = await instancesRes.json() as Array<{
    instance_id: string;
    runs: Array<{ run_id: string; evaluation: { dir: string } | null; mtime: number }>;
  }>;
  const entry = instances.find(i => i.instance_id === instance);
  expect(entry, `[${config} × ${instance}] ${instance} missing from /api/results/instances`).toBeTruthy();

  // Newest `<config>-`-prefixed run by mtime so we don't accidentally
  // read a stale evaluation from a previous iteration.
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
  expect(evalRes.ok, `[${config} × ${instance}] /api/results/evaluation should respond 2xx`).toBe(true);
  const evaluation = await evalRes.json() as {
    report: Record<string, { resolved?: boolean }>;
  };
  const report = evaluation.report?.[instance];
  expect(report, `[${config} × ${instance}] report.json missing entry for ${instance}`).toBeTruthy();
  expect(
    report?.resolved,
    `[${config} × ${instance}] not resolved: report=${JSON.stringify(report)}`,
  ).toBe(true);
}

/** Drive inference only and assert a non-empty `model_patch`. Used for
 * subset=custom rows where the harness can't score the run. Mirrors
 * the body of the old custom-evomas-test-instance spec. */
async function runInferenceOnly(
  config: string, instance: string, hint?: string,
): Promise<void> {
  const events = await streamSSE(`${API}/inference/run`, {
    config,
    instance_ids: [instance],
  });

  const errorEvent = events.find(e => e.type === 'error');
  expect(
    errorEvent,
    `[${config} × ${instance}] inference errored: ${(errorEvent?.['message'] as string) ?? ''}`,
  ).toBeUndefined();

  const inferenceDone = events.find(e => e.type === 'done');
  expect(inferenceDone, `[${config} × ${instance}] inference must reach a 'done' SSE event`).toBeTruthy();

  // Preferred path: `instance_done` carries the per-instance patch inline.
  const instanceDone = events.find(
    e => e.type === 'instance_done' && e['instance_id'] === instance,
  );
  expect(instanceDone, `[${config} × ${instance}] no instance_done event for ${instance}`).toBeTruthy();

  const inlinePatch = instanceDone?.['patch'];
  if (typeof inlinePatch === 'string' && inlinePatch.trim().length > 0) {
    if (hint && !inlinePatch.includes(hint)) {
      // eslint-disable-next-line no-console
      console.warn(`[${config} × ${instance}] patch did not mention ${hint}; full patch:\n${inlinePatch}`);
    }
    return;
  }

  // Fallback: older workers may not include `patch` on instance_done.
  const outputPath = inferenceDone?.['output_path'] as string | undefined;
  expect(outputPath, `[${config} × ${instance}] 'done' event must carry an output_path`).toBeTruthy();
  const predRes = await fetch(
    `${API}/results/prediction?path=${encodeURIComponent(outputPath!)}&instance_id=${encodeURIComponent(instance)}`,
  );
  expect(predRes.ok, `[${config} × ${instance}] /api/results/prediction should respond 2xx`).toBe(true);
  const pred = await predRes.json() as { data?: { model_patch?: string } };
  const modelPatch = pred.data?.model_patch ?? '';
  expect(
    modelPatch.trim().length,
    `[${config} × ${instance}] prediction's model_patch is empty`,
  ).toBeGreaterThan(0);
}

// ─── Matrix ───────────────────────────────────────────────────────────

describe.skipIf(!RUN)('integration · predefined configs', () => {
  for (const config of CONFIGS) {
    describe(config, () => {
      for (const inst of EVAL_INSTANCES) {
        it(
          `resolves ${inst.id} (inference + SWE-bench harness)`,
          async () => { await runInferenceWithEval(config, inst.id); },
          TEST_TIMEOUT_MS,
        );
      }
      for (const inst of INFERENCE_ONLY_INSTANCES) {
        it(
          `produces a non-empty model_patch for ${inst.id} (inference-only)`,
          async () => { await runInferenceOnly(config, inst.id, inst.hint); },
          TEST_TIMEOUT_MS,
        );
      }
    });
  }
});
