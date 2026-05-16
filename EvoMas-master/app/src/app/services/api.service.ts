import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  UnifiedConfig, ConfigSummary, Instance, InferenceEvent, EvalEvent,
  ResultInstance, ResultPrediction, ResultEvaluation, ToolDescriptor,
  AgentType, AgentVariant, PredictionInspection,
} from '../models/types';

const BASE = 'http://localhost:8000/api';

@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient) {}

  // ─── Health (used by the navbar's API indicator) ──────────────────
  getHealth(): Observable<{ status: string }> {
    return this.http.get<{ status: string }>(`${BASE}/health`);
  }

  /** Hostname:port portion of BASE (without the `/api` suffix). */
  get apiHost(): string {
    return BASE.replace(/\/?api\/?$/, '').replace(/^https?:\/\//, '');
  }

  // ─── Models ───────────────────────────────────────────────────────
  getModels(): Observable<string[]> {
    return this.http.get<string[]>(`${BASE}/models`);
  }

  // ─── MCP tools ────────────────────────────────────────────────────
  getTools(): Observable<ToolDescriptor[]> {
    return this.http.get<ToolDescriptor[]>(`${BASE}/tools`);
  }

  // ─── Agent types ──────────────────────────────────────────────────
  getAgentTypes(): Observable<AgentType[]> {
    return this.http.get<AgentType[]>(`${BASE}/agent-types`);
  }

  /** Same data the `variants` field of `getAgentTypes()` already carries,
   * but flat / keyed by AGENT_TYPE -- convenient for callers that only
   * need the variants list. The first entry in each bucket is the EvoMas
   * built-in (the default selection for the Topology dropdown). */
  getAgentVariants(): Observable<Record<string, AgentVariant[]>> {
    return this.http.get<Record<string, AgentVariant[]>>(`${BASE}/agent-variants`);
  }

  // ─── Unified Configs ──────────────────────────────────────────────
  getConfigs(): Observable<ConfigSummary[]> {
    return this.http.get<ConfigSummary[]>(`${BASE}/configs`);
  }

  getConfig(name: string): Observable<UnifiedConfig> {
    return this.http.get<UnifiedConfig>(`${BASE}/configs/${name}`);
  }

  /** Persist a user-loaded config under evomas/config/loaded/<name>.json.
   * Returns 409 when the name collides — the caller can retry with
   * `replace: true` to confirm overwrite. Predefined-config collisions
   * always fail (predefined are read-only). */
  saveLoadedConfig(name: string, data: unknown, replace = false): Observable<{ ok: boolean; stem: string; path: string }> {
    return this.http.post<{ ok: boolean; stem: string; path: string }>(
      `${BASE}/configs/loaded`, { name, data, replace },
    );
  }

  renameLoadedConfig(name: string, newName: string): Observable<{ ok: boolean; stem: string }> {
    return this.http.patch<{ ok: boolean; stem: string }>(
      `${BASE}/configs/loaded/${encodeURIComponent(name)}`, { new_name: newName },
    );
  }

  deleteLoadedConfig(name: string): Observable<{ ok: boolean; stem: string }> {
    return this.http.delete<{ ok: boolean; stem: string }>(
      `${BASE}/configs/loaded/${encodeURIComponent(name)}`,
    );
  }

  /** NDJSON SSE-event transcript saved alongside the prediction file by the
   * inference worker. Returns `exists: false` for older runs that have no log. */
  getResultPredictionConfig(path: string): Observable<{ path: string; name: string; exists: boolean; raw: string }> {
    return this.http.get<{ path: string; name: string; exists: boolean; raw: string }>(
      `${BASE}/results/prediction/config?path=${encodeURIComponent(path)}`,
    );
  }

  // ─── Instances ────────────────────────────────────────────────────
  getInstances(skip = 0, limit = 100): Observable<Instance[]> {
    return this.http.get<Instance[]>(`${BASE}/instances?skip=${skip}&limit=${limit}`);
  }

  countInstances(): Observable<{ count: number }> {
    return this.http.get<{ count: number }>(`${BASE}/instances/count`);
  }

  // ─── Predictions ──────────────────────────────────────────────────
  getPredictions(): Observable<string[]> {
    return this.http.get<string[]>(`${BASE}/predictions`);
  }

  inspectPrediction(path: string): Observable<PredictionInspection> {
    return this.http.get<PredictionInspection>(
      `${BASE}/predictions/inspect?path=${encodeURIComponent(path)}`,
    );
  }

  // ─── Results browser ──────────────────────────────────────────────
  getResultInstances(): Observable<ResultInstance[]> {
    return this.http.get<ResultInstance[]>(`${BASE}/results/instances`);
  }

  getResultPrediction(path: string, instanceId?: string): Observable<ResultPrediction> {
    let url = `${BASE}/results/prediction?path=${encodeURIComponent(path)}`;
    if (instanceId) url += `&instance_id=${encodeURIComponent(instanceId)}`;
    return this.http.get<ResultPrediction>(url);
  }

  /** NDJSON SSE-event transcript saved alongside the prediction file by the
   * inference worker. Returns `exists: false` for older runs that have no log. */
  getResultPredictionLog(path: string): Observable<{ path: string; name: string; exists: boolean; raw: string }> {
    return this.http.get<{ path: string; name: string; exists: boolean; raw: string }>(
      `${BASE}/results/prediction/log?path=${encodeURIComponent(path)}`,
    );
  }

  /** Internal NDJSON SSE-event log saved under `evomas/logs/inference_logs/`
   * by the inference worker — same stream the Inference page consumes live.
   * Returned for completed runs so the Results-page modal can replay them
   * as agent cards + hand-off chips with full fidelity. */
  getResultPredictionNdjson(path: string): Observable<{ path: string; name: string; exists: boolean; raw: string }> {
    return this.http.get<{ path: string; name: string; exists: boolean; raw: string }>(
      `${BASE}/results/prediction/ndjson?path=${encodeURIComponent(path)}`,
    );
  }

  getResultEvaluation(dir: string): Observable<ResultEvaluation> {
    return this.http.get<ResultEvaluation>(`${BASE}/results/evaluation?dir=${encodeURIComponent(dir)}`);
  }

  getResultEvaluationLog(dir: string, name: string): Observable<{ name: string; content: string }> {
    return this.http.get<{ name: string; content: string }>(
      `${BASE}/results/evaluation/log?dir=${encodeURIComponent(dir)}&name=${encodeURIComponent(name)}`
    );
  }

  getResultEvaluationZipUrl(dir: string): string {
    return `${BASE}/results/evaluation/zip?dir=${encodeURIComponent(dir)}`;
  }

  revealInExplorer(path: string): Observable<{ ok: boolean; path: string }> {
    return this.http.post<{ ok: boolean; path: string }>(`${BASE}/results/reveal`, { path });
  }

  // ─── Refresh SWE-bench instances ──────────────────────────────────
  refreshInstances(
    subset: 'lite' | 'full' | 'verified' = 'lite',
    split: 'dev' | 'test' | 'train' = 'dev',
    limit?: number,
  ): Observable<{ count: number; subset: string; split: string; path: string }> {
    const params = new URLSearchParams({ subset, split, append: 'true' });
    if (limit !== undefined) params.set('limit', String(limit));
    return this.http.post<{ count: number; subset: string; split: string; path: string }>(
      `${BASE}/instances/refresh?${params.toString()}`, {},
    );
  }

  /** Append a user-provided GitHub repo as an instance. The backend writes a
   * subset=custom row to swebench_instances.jsonl; the Evaluation page
   * filters those rows out before invoking the SWE-bench harness. */
  addCustomInstance(repo: string, problem_statement: string, base_commit?: string): Observable<{
    instance_id: string; repo: string; base_commit: string; duplicate: boolean;
  }> {
    return this.http.post<{ instance_id: string; repo: string; base_commit: string; duplicate: boolean }>(
      `${BASE}/instances/custom`,
      { repo, problem_statement, base_commit: base_commit || null },
    );
  }

  /** Pull every (subset, split) pair from HuggingFace in one server-side
   * call. Slow (Full alone is huge); the caller should disable the refresh
   * button while this is in flight. */
  refreshAllInstances(limit?: number): Observable<{
    total: number;
    results: Record<string, { count?: number; error?: string }>;
  }> {
    const params = new URLSearchParams();
    if (limit !== undefined) params.set('limit', String(limit));
    const qs = params.toString();
    return this.http.post<{ total: number; results: Record<string, { count?: number; error?: string }> }>(
      `${BASE}/instances/refresh-all${qs ? '?' + qs : ''}`, {},
    );
  }

  // ─── Inference SSE (POST + ReadableStream) ────────────────────────
  streamInference(
    instanceIds: string | string[],
    config: string | UnifiedConfig,
  ): Observable<InferenceEvent> {
    const ids = Array.isArray(instanceIds) ? instanceIds : [instanceIds];
    return new Observable<InferenceEvent>(observer => {
      const controller = new AbortController();
      fetch(`${BASE}/inference/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instance_ids: ids, config }),
        signal: controller.signal,
      }).then(async res => {
        const reader = res.body!.getReader();
        const dec = new TextDecoder();
        let buf = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) { observer.complete(); break; }
          buf += dec.decode(value, { stream: true });
          const lines = buf.split('\n');
          buf = lines.pop() ?? '';
          for (const line of lines) {
            const t = line.trim();
            if (t.startsWith('data: ')) {
              try { observer.next(JSON.parse(t.slice(6))); } catch {}
            }
          }
        }
      }).catch(err => {
        if (err.name !== 'AbortError') observer.error(err);
        else observer.complete();
      });
      return () => controller.abort();
    });
  }

  cancelInference(instanceId: string): Observable<{ ok: boolean }> {
    return this.http.post<{ ok: boolean }>(`${BASE}/inference/cancel/${instanceId}`, {});
  }

  getActiveInference(): Observable<{
    active: boolean;
    run_id?: string;
    config_label?: string;
    instance_ids?: string[];
    log_path?: string;
    started_at?: number;
  }> {
    return this.http.get<{
      active: boolean;
      run_id?: string;
      config_label?: string;
      instance_ids?: string[];
      log_path?: string;
      started_at?: number;
    }>(`${BASE}/inference/active`);
  }

  /** Return the slice of `path` after `offset` bytes, plus the new offset and
   * whether the run is still in flight. The Inference page polls this on
   * reload to recover live state without an SSE re-attach. */
  getInferenceLogTail(path: string, offset: number): Observable<{ raw: string; offset: number; is_running: boolean }> {
    return this.http.get<{ raw: string; offset: number; is_running: boolean }>(
      `${BASE}/inference/log-tail?path=${encodeURIComponent(path)}&offset=${offset}`,
    );
  }

  cancelEvaluation(predictionsPath: string): Observable<{ ok: boolean }> {
    return this.http.post<{ ok: boolean }>(`${BASE}/evaluation/cancel?predictions_path=${encodeURIComponent(predictionsPath)}`, {});
  }

  // ─── Evaluation SSE ───────────────────────────────────────────────
  streamEvaluation(predictionsPath: string, split: string, maxWorkers: number, runId: string): Observable<EvalEvent> {
    return new Observable<EvalEvent>(observer => {
      const controller = new AbortController();
      // Omit `split` and `run_id` when blank so the backend auto-detects from
      // the prediction file (per-line `subset`/`split`).
      const body: Record<string, unknown> = {
        predictions_path: predictionsPath,
        max_workers: maxWorkers,
      };
      if (split) body['split'] = split;
      if (runId) body['run_id'] = runId;
      fetch(`${BASE}/evaluation/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      }).then(async res => {
        const reader = res.body!.getReader();
        const dec = new TextDecoder();
        let buf = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) { observer.complete(); break; }
          buf += dec.decode(value, { stream: true });
          const lines = buf.split('\n');
          buf = lines.pop() ?? '';
          for (const line of lines) {
            const t = line.trim();
            if (t.startsWith('data: ')) {
              try { observer.next(JSON.parse(t.slice(6))); } catch {}
            }
          }
        }
      }).catch(err => {
        if (err.name !== 'AbortError') observer.error(err);
        else observer.complete();
      });
      return () => controller.abort();
    });
  }
}
