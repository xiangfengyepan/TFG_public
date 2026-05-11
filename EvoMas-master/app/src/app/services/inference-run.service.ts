import { Injectable } from '@angular/core';
import { Subject, Subscription, timer } from 'rxjs';
import { ApiService } from './api.service';
import { InferenceEvent, AGENT_COLORS, AGENT_LABELS, UnifiedConfig } from '../models/types';

const LOG_POLL_INTERVAL_MS = 1500;

export interface ToolCallEntry {
  tool: string;
  argsPreview: string;
  resultPreview: string;
}

export interface AgentCard {
  agent: string;
  label: string;
  color: string;
  status: 'running' | 'done' | 'error';
  delta: Record<string, unknown>;
  expanded: boolean;
  thinkingStream: string;
  toolCalls: ToolCallEntry[];
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
    toolCalls: [],
  };
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
          this.instances = snap.instance_ids.map(id => ({
            instance_id: id,
            status: 'queued',
            cards: [],
            finalPatch: '',
            outputPath: '',
            runId: snap.run_id ?? '',
            errorMsg: '',
            errorTraceback: '',
          }));
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
    this.instances = ids.map(id => ({
      instance_id: id,
      status: 'queued',
      cards: [],
      finalPatch: '',
      outputPath: '',
      runId: '',
      errorMsg: '',
      errorTraceback: '',
    }));
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

  /** Latest card for `agent` that's still open (running). Used so a thinking
   * chunk / tool call lands on the in-flight attempt rather than retrofitting
   * a previous, completed retry. Returns null once that attempt's
   * `agent_event` (the closing event) has flipped its status to 'done'. */
  private openCard(inst: RunInstance, agent: string): AgentCard | null {
    for (let i = inst.cards.length - 1; i >= 0; i--) {
      if (inst.cards[i].agent === agent && inst.cards[i].status === 'running') {
        return inst.cards[i];
      }
    }
    return null;
  }

  /** Append a fresh card for the agent. The label is suffixed with
   * "(retry N)" when this is the 2nd+ attempt so the panel makes the retry
   * sequence visually obvious. */
  private spawnCard(inst: RunInstance, agent: string): AgentCard {
    const previous = inst.cards.filter(c => c.agent === agent).length;
    const card = newCard(agent, this.nodeColors);
    if (previous > 0) card.label = `${card.label} (retry ${previous + 1})`;
    inst.cards.push(card);
    return card;
  }

  private handleEvent(ev: InferenceEvent): void {
    switch (ev.type) {
      case 'status':
        this.statusMsg = ev.message ?? '';
        break;

      case 'instance_start': {
        const inst = this.getInstance(ev.instance_id);
        if (inst) {
          inst.status = 'running';
          inst.cards = [];
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
        if (inst) {
          inst.status = 'done';
          if (ev.output_path) inst.outputPath = ev.output_path;
          if (ev.run_id) inst.runId = ev.run_id;
          if (ev.patch) inst.finalPatch = ev.patch;
        }
        this.statusMsg = `Finished ${ev.instance_id} (${(ev.index ?? 0) + 1}/${ev.total ?? 1})`;
        break;
      }

      case 'start':
        this.statusMsg = `Running ${ev.config} on ${ev.instance_id}…`;
        break;

      case 'agent_event': {
        // Each agent_event marks the END of one node visit. Manager retries
        // (e.g. routing back to the patcher after validation fails) show up
        // as repeated visits to the same node — render each as its own card
        // so the user sees per-attempt thinking / tools / patches separately.
        const inst = this.runningInst();
        if (!inst) return;
        const agent = ev.agent ?? 'unknown';
        const open = this.openCard(inst, agent);
        const card = open ?? this.spawnCard(inst, agent);
        card.delta = open ? { ...card.delta, ...(ev.delta ?? {}) } : (ev.delta ?? {});
        card.status = 'done';
        break;
      }

      case 'thinking_chunk': {
        const inst = this.runningInst();
        if (!inst) return;
        const agent = ev.agent ?? 'unknown';
        const open = this.openCard(inst, agent);
        const card = open ?? this.spawnCard(inst, agent);
        card.thinkingStream += ev.chunk ?? '';
        break;
      }

      case 'tool_call': {
        const inst = this.runningInst();
        if (!inst) return;
        const agent = ev.agent ?? 'unknown';
        const open = this.openCard(inst, agent);
        const card = open ?? this.spawnCard(inst, agent);
        card.toolCalls.push({
          tool: ev.tool ?? '',
          argsPreview: ev.args_preview ?? '',
          resultPreview: ev.result_preview ?? '',
        });
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
        if (inst) {
          inst.errorMsg = ev.message ?? '';
          inst.errorTraceback = ev.traceback ?? '';
        }
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
