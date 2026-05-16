import { Injectable } from '@angular/core';
import { Subject, Subscription, timer } from 'rxjs';
import { ApiService } from './api.service';
import { AgentType, InferenceEvent, AGENT_COLORS, AGENT_LABELS, HandoffChip, UnifiedConfig } from '../models/types';

/** Build the per-node colour map for one run from the active config plus
 * the /api/agent-types catalog. Used by:
 *   - the live Inference page (`refreshNodeColors`),
 *   - the Results-page modal (`parseNdjsonToRunInstance` callers),
 * so the card-dot colour matches the agent's `class` field regardless
 * of which page is rendering. Extracted from `InferenceComponent` so it
 * doesn't drift across the two consumers. */
export function buildNodeColors(
  cfg: Pick<UnifiedConfig, 'agents'>,
  agentTypes: AgentType[],
): Record<string, string> {
  // Two lookups off the agent-types catalog so the JSON's `class` field
  // can be either the human-readable AGENT_TYPE label ("Locator",
  // "Helper/Proxy", …) OR the Python class name ("LocatorAgent",
  // "HelperProxyAgent", …) — the backend registers both and topology
  // JSONs in this repo use a mix.
  const byClass: Record<string, string> = {};
  const byType:  Record<string, string> = {};
  for (const t of agentTypes) {
    byClass[t.class] = t.color;
    byType[t.type]   = t.color;
  }
  // LLMToolAgent is the generic config-driven base — colour it as a Base agent.
  const aliasToType: Record<string, string> = { LLMToolAgent: 'Base agent' };
  const out: Record<string, string> = {};
  for (const [node, block] of Object.entries(cfg.agents ?? {})) {
    const cls = (block as { class?: string })?.class ?? '';
    const color = byClass[cls]
               ?? byType[cls]
               ?? byType[aliasToType[cls] ?? '']
               ?? '';
    if (color) out[node] = color;
  }
  return out;
}

const LOG_POLL_INTERVAL_MS = 1500;

export interface ToolCallEntry {
  tool: string;
  argsPreview: string;
  resultPreview: string;
}

export interface AgentTokenUsage {
  input: number;
  output: number;
  total: number;
}

export interface AgentCard {
  agent: string;
  label: string;
  color: string;
  status: 'running' | 'done' | 'error';
  delta: Record<string, unknown>;
  expanded: boolean;
  thinkingStream: string;
  responseStream: string;
  toolCalls: ToolCallEntry[];
  inputs: Record<string, unknown>;
  tokens: AgentTokenUsage | null;
}

/** Per-instance state inside the active run. The cards/finalPatch buffer here
 * so the user can switch between instances inside the run (chip click) and
 * see each one's full execution log without losing the others. */
export interface RunInstance {
  instance_id: string;
  status: 'queued' | 'running' | 'done' | 'error' | 'cancelled';
  cards: AgentCard[];
  finalPatch: string;
  outputPath: string;
  runId: string;
  errorMsg: string;
  errorTraceback: string;
  /** Hand-off chips keyed by their *target* agent. Used by the inference
   * page to render chips immediately BEFORE the target's card. One entry
   * per outgoing edge — a fan-out source produces multiple chips, each
   * with its own target. */
  handoffsByTarget: Record<string, HandoffChip[]>;
}

export type RunStatus = 'idle' | 'running' | 'done' | 'cancelled' | 'error';

function newCard(agent: string, nodeColors: Record<string, string>): AgentCard {
  return {
    agent,
    label: AGENT_LABELS[agent] ?? agent,
    // Per-run color map (built from the resolved config's `agents.<n>.class`
    // looked up against /api/agent-types) wins; fall back to the legacy
    // node-id-keyed AGENT_COLORS so evo-star nodes keep their colors when
    // the inference page hasn't loaded a config yet.
    color: nodeColors[agent] ?? AGENT_COLORS[agent] ?? '#888',
    status: 'running',
    delta: {},
    expanded: true,
    thinkingStream: '',
    responseStream: '',
    toolCalls: [],
    inputs: {},
    tokens: null,
  };
}

/** Factory for a fresh RunInstance — shared by the live service init and
 * by `parseNdjsonToRunInstance` so the snapshot the Results-page modal
 * renders matches the live-page shape byte-for-byte. */
export function newRunInstance(
  instanceId: string,
  status: RunInstance['status'] = 'queued',
  runId = '',
): RunInstance {
  return {
    instance_id: instanceId,
    status,
    cards: [],
    finalPatch: '',
    outputPath: '',
    runId,
    errorMsg: '',
    errorTraceback: '',
    handoffsByTarget: {},
  };
}

/** Most-recent still-running card for `agent`, used so a thinking chunk
 * / tool call lands on the in-flight attempt rather than retrofitting a
 * previous, completed retry. Mirrors `InferenceRunService.openCard`. */
function _openCard(inst: RunInstance, agent: string): AgentCard | null {
  for (let i = inst.cards.length - 1; i >= 0; i--) {
    if (inst.cards[i].agent === agent && inst.cards[i].status === 'running') {
      return inst.cards[i];
    }
  }
  return null;
}

/** Append a fresh card for `agent` to `inst.cards`. The label gets a
 * "(retry N)" suffix on the 2nd+ visit so the panel reads as a sequence. */
function _spawnCard(
  inst: RunInstance,
  agent: string,
  nodeColors: Record<string, string>,
): AgentCard {
  const previous = inst.cards.filter(c => c.agent === agent).length;
  const card = newCard(agent, nodeColors);
  if (previous > 0) card.label = `${card.label} (retry ${previous + 1})`;
  inst.cards.push(card);
  return card;
}

/** Pure reducer: apply a single SSE/NDJSON event to one RunInstance.
 *
 * Only per-instance mutations live here (cards, hand-off chips, status
 * flags, error message). Service-level state (statusMsg, this.status,
 * selectedInstanceId, run-level `done`/`cancelled` semantics) stays in
 * `InferenceRunService.handleEvent` because the Results-page modal
 * replays a *completed* run — there's no live `status` to track.
 *
 * Used by both the live `handleEvent` and the static `parseNdjsonToRunInstance`. */
export function applyEventToInstance(
  inst: RunInstance,
  ev: InferenceEvent,
  nodeColors: Record<string, string> = {},
): void {
  switch (ev.type) {
    case 'instance_start':
      inst.status = 'running';
      inst.cards = [];
      inst.handoffsByTarget = {};
      break;

    case 'instance_done':
      inst.status = 'done';
      if (ev.output_path) inst.outputPath = ev.output_path;
      if (ev.run_id) inst.runId = ev.run_id;
      if (ev.patch) inst.finalPatch = ev.patch;
      break;

    case 'agent_event': {
      const agent = ev.agent ?? 'unknown';
      const open = _openCard(inst, agent);
      const card = open ?? _spawnCard(inst, agent, nodeColors);
      card.delta = open ? { ...card.delta, ...(ev.delta ?? {}) } : (ev.delta ?? {});
      card.status = 'done';
      break;
    }

    case 'handoff': {
      const target = ev.to ?? '';
      if (!target) break;
      const chip: HandoffChip = {
        from: ev.from ?? 'unknown',
        to: target,
        summary: ev.summary ?? '',
        preview: ev.preview ?? '',
        keys: ev.keys ?? [],
        timestamp: ev.timestamp ?? '',
      };
      (inst.handoffsByTarget[target] ||= []).push(chip);
      break;
    }

    case 'thinking_chunk': {
      const agent = ev.agent ?? 'unknown';
      const open = _openCard(inst, agent);
      const card = open ?? _spawnCard(inst, agent, nodeColors);
      card.thinkingStream += ev.chunk ?? '';
      break;
    }

    case 'response': {
      const agent = ev.agent ?? 'unknown';
      const open = _openCard(inst, agent);
      const card = open ?? _spawnCard(inst, agent, nodeColors);
      const text = ev.content ?? '';
      if (text) {
        card.responseStream = card.responseStream
          ? card.responseStream + '\n\n─────\n\n' + text
          : text;
      }
      break;
    }

    case 'agent_input': {
      const agent = ev.agent ?? 'unknown';
      const open = _openCard(inst, agent);
      const card = open ?? _spawnCard(inst, agent, nodeColors);
      card.inputs = (ev.inputs as Record<string, unknown>) ?? {};
      break;
    }

    case 'agent_tokens': {
      const agent = ev.agent ?? 'unknown';
      for (const card of inst.cards) {
        if (card.agent === agent) {
          card.tokens = {
            input:  Number(ev['input']  ?? 0),
            output: Number(ev['output'] ?? 0),
            total:  Number(ev['total']  ?? 0),
          };
        }
      }
      break;
    }

    case 'tool_call': {
      const agent = ev.agent ?? 'unknown';
      const open = _openCard(inst, agent);
      const card = open ?? _spawnCard(inst, agent, nodeColors);
      card.toolCalls.push({
        tool: ev.tool ?? '',
        argsPreview: ev.args_preview ?? '',
        resultPreview: ev.result_preview ?? '',
      });
      break;
    }

    case 'error':
      inst.errorMsg = ev.message ?? '';
      inst.errorTraceback = ev.traceback ?? '';
      break;

    // status / start / done / cancelled / run_id are service-level only
    // (no per-instance mutation). run_id targets multiple instances at
    // the service layer; the static parser doesn't need it because the
    // NDJSON's `instance_done` carries the final runId.
  }
}

/** Replay a completed run's NDJSON event log into a snapshot RunInstance.
 *
 * Multi-instance batches: if `instanceId` is non-empty, only events that
 * are scoped to that instance (`ev.instance_id === instanceId`) OR that
 * are instance-unscoped (`thinking_chunk` / `tool_call` etc., which the
 * worker emits between `instance_start`/`instance_done` for the active
 * one) are applied.
 *
 * Falls back to `status='done'` if the file never emitted an
 * `instance_start` — older runs predating that event still produce a
 * usable card view. */
export function parseNdjsonToRunInstance(
  raw: string,
  instanceId: string,
  nodeColors: Record<string, string> = {},
): RunInstance {
  const inst = newRunInstance(instanceId);
  let activeInstanceId = '';
  let sawInstanceStart = false;

  for (const line of raw.split('\n')) {
    const t = line.trim();
    if (!t) continue;
    let ev: InferenceEvent;
    try { ev = JSON.parse(t) as InferenceEvent; } catch { continue; }

    // Track which instance the worker is currently in: `instance_start`
    // opens a scope; `instance_done` closes it. Unscoped events between
    // them belong to that instance.
    if (ev.type === 'instance_start' && ev.instance_id) {
      activeInstanceId = ev.instance_id;
      sawInstanceStart = true;
    }

    // Skip events scoped to a different instance.
    if (instanceId) {
      if (ev.instance_id && ev.instance_id !== instanceId) {
        if (ev.type === 'instance_done' && ev.instance_id === activeInstanceId) {
          activeInstanceId = '';
        }
        continue;
      }
      // Unscoped event (no instance_id field): apply only if the active
      // worker scope matches our target instance.
      if (!ev.instance_id && activeInstanceId && activeInstanceId !== instanceId) {
        continue;
      }
    }

    applyEventToInstance(inst, ev, nodeColors);

    if (ev.type === 'instance_done' && ev.instance_id) {
      activeInstanceId = '';
    }
  }

  // If the file never emitted instance_start, the snapshot defaults to
  // 'queued' which reads wrong on a completed run. Flip to 'done'.
  if (!sawInstanceStart && inst.status === 'queued') {
    inst.status = 'done';
  }
  return inst;
}

/** Single-run inference. One run at a time — a run is an SSE stream that
 * processes N instances sequentially server-side. While a run is in flight,
 * `run()` is a no-op until the user cancels or it completes naturally. */
@Injectable({ providedIn: 'root' })
export class InferenceRunService {
  status: RunStatus = 'idle';
  config: string | UnifiedConfig = '';
  configLabel = '';
  startedAt = 0;
  instances: RunInstance[] = [];
  selectedInstanceId: string | null = null;
  errorMsg = '';
  statusMsg = '';

  /** Per-run map from node name → hex color, derived by the inference page
   * from the resolved config's `agents.<n>.class` looked up against the
   * /api/agent-types catalog. Cards consult this when first created so the
   * agent dot picks up the type's color (works for any config, not just
   * the legacy evo-star nodes baked into AGENT_COLORS). */
  nodeColors: Record<string, string> = {};

  readonly changed = new Subject<void>();
  private sub?: Subscription;

  // Resume-from-log state. When the page loads with a run still in flight on
  // the backend (e.g. browser reloaded mid-run), we replay the on-disk
  // transcript and switch to polling the .log for new events instead of
  // attaching an SSE stream.
  private logPath: string | null = null;
  private logOffset = 0;
  private pollSub?: Subscription;
  private logBuffer = '';

  constructor(private api: ApiService) {
    this.attach();
  }

  // ─── Selection / convenience getters ──────────────────────────
  get running(): boolean { return this.status === 'running'; }
  get cancelled(): boolean { return this.status === 'cancelled'; }

  get currentInstance(): RunInstance | null {
    return this.instances.find(i => i.instance_id === this.selectedInstanceId)
        ?? this.instances.find(i => i.status === 'running')
        ?? this.instances[0]
        ?? null;
  }

  get cards(): AgentCard[] { return this.currentInstance?.cards ?? []; }
  get finalPatch(): string { return this.currentInstance?.finalPatch ?? ''; }
  get outputPath(): string { return this.currentInstance?.outputPath ?? ''; }
  get errorTraceback(): string { return this.currentInstance?.errorTraceback ?? ''; }
  get progress(): RunInstance[] { return this.instances; }

  selectInstance(id: string): void {
    this.selectedInstanceId = id;
    this.notify();
  }

  clear(): void {
    if (this.status === 'running') return;
    this.status = 'idle';
    this.instances = [];
    this.selectedInstanceId = null;
    this.errorMsg = '';
    this.statusMsg = '';
    this.notify();
  }

  // ─── Live-stream lifecycle (attach on inference page enter, ──
  //                              detach on leave) ──────────────────
  /** Bring the service in sync with the backend's `_active_run` snapshot
   * and start polling the .log so the Inference page sees live events.
   *
   * Called from:
   *   1. The constructor — once at app boot, handles the page-reload case.
   *   2. `InferenceComponent.ngOnInit` — every time the user re-enters the
   *      Inference page after a previous `detach()`.
   *
   * If we're already streaming SSE for this run (the user kicked off a
   * `run()` and never left the page), this is a no-op — the SSE is faster
   * than the 1.5 s polling tick, so we don't downgrade.
   *
   * If the backend's active run matches our locally-held one (same
   * `run_id`), we preserve the existing `logOffset` and just resume the
   * polling timer — events that arrived during the gap are picked up on
   * the next tick. Otherwise we reset the local replay state and start
   * from offset 0 (full transcript replay rebuilds cards from scratch). */
  attach(): void {
    if (this.sub && this.status === 'running') return;
    this.api.getActiveInference().subscribe({
      next: snap => {
        if (!snap.active || !snap.log_path || !snap.instance_ids) return;
        const sameRun =
          !!snap.run_id &&
          this.instances.length > 0 &&
          this.instances[0]?.runId === snap.run_id;
        if (!sameRun) {
          this.config = snap.config_label ?? '';
          this.configLabel = snap.config_label ?? '(active)';
          this.startedAt = snap.started_at ?? Date.now();
          this.errorMsg = '';
          this.status = 'running';
          this.instances = snap.instance_ids.map(id =>
            newRunInstance(id, 'queued', snap.run_id ?? ''),
          );
          this.selectedInstanceId = snap.instance_ids[0] ?? null;
          this.statusMsg = `Reattaching to run ${snap.run_id ?? ''}…`;
          this.logOffset = 0;
          this.logBuffer = '';
        }
        this.logPath = snap.log_path;
        this.notify();
        this.startLogPolling();
      },
      error: () => { /* server unreachable; nothing to resume */ },
    });
  }

  /** Tear down the live SSE subscription + log polling without touching
   * instance state. Called from `InferenceComponent.ngOnDestroy` when the
   * user navigates away from the Inference page so the SSE microtask
   * stream stops saturating the main thread (which was blocking the
   * Topology page's cytoscape layout from measuring its host correctly).
   * The frozen instances/cards stay visible if the user comes back. */
  detach(): void {
    this.sub?.unsubscribe();
    this.sub = undefined;
    this.stopLogPolling();
  }

  private startLogPolling(): void {
    this.stopLogPolling();
    if (!this.logPath) return;
    this.pollSub = timer(0, LOG_POLL_INTERVAL_MS).subscribe(() => this.pollLog());
  }

  private stopLogPolling(): void {
    this.pollSub?.unsubscribe();
    this.pollSub = undefined;
  }

  private pollLog(): void {
    if (!this.logPath) { this.stopLogPolling(); return; }
    this.api.getInferenceLogTail(this.logPath, this.logOffset).subscribe({
      next: chunk => {
        this.logOffset = chunk.offset;
        // Buffer + split on newlines so we don't try to JSON.parse a partial
        // line at the end of the chunk.
        this.logBuffer += chunk.raw;
        const lines = this.logBuffer.split('\n');
        this.logBuffer = lines.pop() ?? '';
        for (const line of lines) {
          const t = line.trim();
          if (!t) continue;
          try { this.handleEvent(JSON.parse(t) as InferenceEvent); } catch { /* skip malformed */ }
        }
        if (!chunk.is_running) {
          // Final flush on any trailing line, then stop polling.
          if (this.logBuffer.trim()) {
            try { this.handleEvent(JSON.parse(this.logBuffer.trim()) as InferenceEvent); } catch {}
            this.logBuffer = '';
          }
          if (this.status === 'running') this.status = 'done';
          this.logPath = null;
          this.stopLogPolling();
        }
        this.notify();
      },
      error: () => { /* transient — keep polling */ },
    });
  }

  // ─── Run / cancel ─────────────────────────────────────────────
  run(instanceIds: string | string[], config: string | UnifiedConfig): void {
    if (this.status === 'running') return;            // ignore overlapping clicks
    const ids = Array.isArray(instanceIds) ? instanceIds : [instanceIds];
    if (ids.length === 0) return;

    this.config = config;
    this.configLabel = typeof config === 'string'
      ? (config || '(unsaved)')
      : (config.id || '(session)');
    this.status = 'running';
    this.startedAt = Date.now();
    this.errorMsg = '';
    this.instances = ids.map(id => newRunInstance(id));
    this.selectedInstanceId = ids[0] ?? null;
    this.statusMsg = `Running ${this.configLabel} (${ids.length} instance${ids.length > 1 ? 's' : ''})`;
    this.notify();

    this.sub = this.api.streamInference(ids, config).subscribe({
      next: ev => { this.handleEvent(ev); this.notify(); },
      error: err => {
        this.status = 'error';
        this.errorMsg = err?.message ?? 'Connection error';
        this.notify();
      },
      complete: () => {
        if (this.status === 'running') this.status = 'done';
        this.notify();
      },
    });
  }

  cancel(): void {
    if (this.status !== 'running') return;
    this.sub?.unsubscribe();
    for (const inst of this.instances) {
      if (inst.status === 'queued' || inst.status === 'running') {
        inst.status = 'cancelled';
        this.api.cancelInference(inst.instance_id).subscribe();
      }
    }
    this.status = 'cancelled';
    this.statusMsg = 'Cancelled by user';
    this.notify();
  }

  // ─── Stream handler ───────────────────────────────────────────
  private getInstance(id: string | undefined | null): RunInstance | null {
    if (!id) return null;
    return this.instances.find(i => i.instance_id === id) ?? null;
  }

  private runningInst(): RunInstance | null {
    return this.instances.find(i => i.status === 'running') ?? null;
  }

  /** Dispatch a live SSE / log-tail event:
   *  - Service-level mutations (statusMsg, this.status, selectedInstanceId,
   *    cross-instance run_id propagation) stay here.
   *  - Per-instance mutations delegate to `applyEventToInstance` so the
   *    Results-page replay path uses the exact same reducer. */
  private handleEvent(ev: InferenceEvent): void {
    switch (ev.type) {
      case 'status':
        this.statusMsg = ev.message ?? '';
        break;

      case 'instance_start': {
        const inst = this.getInstance(ev.instance_id);
        if (inst) {
          applyEventToInstance(inst, ev, this.nodeColors);
          // Auto-focus the running instance unless the user has already
          // clicked into another one.
          if (!this.selectedInstanceId || this.selectedInstanceId === inst.instance_id) {
            this.selectedInstanceId = inst.instance_id;
          }
        }
        this.statusMsg = `Starting ${ev.instance_id} (${(ev.index ?? 0) + 1}/${ev.total ?? 1})`;
        break;
      }

      case 'instance_done': {
        const inst = this.getInstance(ev.instance_id);
        if (inst) applyEventToInstance(inst, ev, this.nodeColors);
        this.statusMsg = `Finished ${ev.instance_id} (${(ev.index ?? 0) + 1}/${ev.total ?? 1})`;
        break;
      }

      case 'start':
        this.statusMsg = `Running ${ev.config} on ${ev.instance_id}…`;
        break;

      case 'agent_event':
      case 'handoff':
      case 'thinking_chunk':
      case 'response':
      case 'agent_input':
      case 'agent_tokens':
      case 'tool_call': {
        const inst = this.runningInst();
        if (!inst) return;
        applyEventToInstance(inst, ev, this.nodeColors);
        break;
      }

      case 'run_id': {
        if (!ev.run_id) break;
        // Mark every queued / running instance with the run_id immediately
        // so the .bp-item chip can display it during execution. instance_done
        // later overwrites with the same value (idempotent). Cross-instance
        // fan-out, so this stays at the service layer rather than per-instance.
        for (const inst of this.instances) {
          if (inst.status === 'queued' || inst.status === 'running') {
            inst.runId = String(ev.run_id);
            if (ev.output_path) inst.outputPath = String(ev.output_path);
          }
        }
        break;
      }

      case 'done':
        this.status = 'done';
        this.statusMsg = `Run complete (${this.instances.length} instance${this.instances.length > 1 ? 's' : ''})`;
        break;

      case 'error': {
        this.status = 'error';
        this.errorMsg = ev.message ?? 'Unknown error';
        const inst = this.runningInst() ?? this.getInstance(this.selectedInstanceId);
        if (inst) applyEventToInstance(inst, ev, this.nodeColors);
        break;
      }

      case 'cancelled':
        this.status = 'cancelled';
        this.statusMsg = 'Cancelled by user';
        break;
    }
  }

  private notify(): void { this.changed.next(); }
}
