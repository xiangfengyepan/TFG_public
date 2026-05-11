import {
  Component, OnInit, OnDestroy, ViewChild,
  ElementRef, AfterViewChecked, ChangeDetectorRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import { ApiService } from '../../services/api.service';
import {
  InferenceRunService, AgentCard, RunInstance,
} from '../../services/inference-run.service';
import { InferenceStateService } from '../../services/inference-state.service';
import { TopologyStateService } from '../../services/topology-state.service';
import { AgentType, Instance, SUBSET_SPLITS, SwebenchSplit, SwebenchSubset, UnifiedConfig, AGENT_COLORS, AGENT_LABELS } from '../../models/types';
import { EvoButtonComponent, EvoSelectComponent, EvoBadgeComponent, EvoBoxComponent, EvoSwitchComponent } from '../../components/index';

@Component({
  selector: 'app-inference',
  standalone: true,
  imports: [CommonModule, FormsModule, EvoButtonComponent, EvoSelectComponent, EvoBadgeComponent, EvoBoxComponent, EvoSwitchComponent],
  templateUrl: './inference.component.html',
  styleUrl: './inference.component.css',
})
export class InferenceComponent implements OnInit, OnDestroy, AfterViewChecked {
  @ViewChild('scrollEl') scrollEl!: ElementRef<HTMLDivElement>;

  // ─── Instances ─────────────────────────────────────────────────
  instances: Instance[] = [];
  filteredInstances: Instance[] = [];
  instancesTotal = 0;
  /** 0 = unlimited. The grouped picker handles thousands of rows fine since
   * each subset/split expander is collapsed by default. */
  instancesPageSize = 0;
  loadingInstances = false;
  refreshing = false;
  refreshError = '';

  // Selection / config / search state lives in InferenceStateService so it
  // survives navigation; see getters/setters below.
  configs: string[] = [];
  showThinking = true;

  readonly agentColors = AGENT_COLORS;
  readonly agentLabels = AGENT_LABELS;

  /** Live catalog from /api/agent-types — used to look up the type color
   * for each node in the active config so the central log panel chips
   * render with the right color regardless of which config is selected. */
  private agentTypes: AgentType[] = [];

  private changeSub?: Subscription;
  shouldScroll = false;

  constructor(
    private api: ApiService,
    public inferSvc: InferenceRunService,
    public state: InferenceStateService,
    public topoState: TopologyStateService,
    private cdr: ChangeDetectorRef,
  ) {}

  // ─── Getters delegating to the run service ─────────────────────
  get running(): boolean { return this.inferSvc.running; }
  get cancelled(): boolean { return this.inferSvc.cancelled; }
  get statusMsg(): string { return this.inferSvc.statusMsg; }
  get cards(): AgentCard[] { return this.inferSvc.cards; }
  get finalPatch(): string { return this.inferSvc.finalPatch; }
  get outputPath(): string { return this.inferSvc.outputPath; }
  get errorMsg(): string { return this.inferSvc.errorMsg; }
  get errorTraceback(): string { return this.inferSvc.errorTraceback; }
  get progress(): RunInstance[] { return this.inferSvc.progress; }

  /** Active-run instance chips (level-2 selector). */
  get runInstances(): RunInstance[] { return this.inferSvc.instances; }
  get currentInstance(): RunInstance | null { return this.inferSvc.currentInstance; }
  selectInstanceInRun(id: string): void { this.inferSvc.selectInstance(id); }
  clearRun(): void { this.inferSvc.clear(); }

  // ─── Selection state (persisted across navigation) ─────────────
  get selectedInstanceIds(): Set<string> { return this.state.selectedInstanceIds; }
  get selectionCount(): number { return this.state.selectedInstanceIds.size; }
  get instanceSearch(): string { return this.state.instanceSearch; }
  set instanceSearch(v: string) { this.state.instanceSearch = v; }
  get config(): string { return this.state.config; }
  set config(v: string) {
    const changed = this.state.config !== v;
    this.state.config = v;
    if (changed) this.refreshNodeColors();
  }
  get instancesPage(): number { return this.state.instancesPage; }
  set instancesPage(v: number) { this.state.instancesPage = v; }

  isSelected(id: string): boolean { return this.state.isSelected(id); }
  toggleInstance(id: string): void { this.state.toggleInstance(id); }
  clearSelection(): void { this.state.clearSelection(); }

  // ─── Subset / split grouping (nested left-panel expanders) ─────
  readonly subsets: SwebenchSubset[] = ['lite', 'full', 'verified'];

  /** Splits actually shipped by each subset on HuggingFace — drives the UI so
   * we don't render an empty `dev` row under Verified or `train` under Lite. */
  splitsFor(s: SwebenchSubset): SwebenchSplit[] { return SUBSET_SPLITS[s]; }

  subsetLabel(s: SwebenchSubset): string {
    return s === 'lite' ? 'Lite' : s === 'full' ? 'Full' : 'Verified';
  }

  /** Filtered instances belonging to (subset, split). The same `instanceSearch`
   * filter applies as on the flat view. */
  instancesIn(subset: SwebenchSubset, split: SwebenchSplit): Instance[] {
    const q = this.instanceSearch.toLowerCase();
    return this.instances.filter(i =>
      i.subset === subset && i.split === split &&
      (!q || i.instance_id.toLowerCase().includes(q) || i.repo.toLowerCase().includes(q))
    );
  }
  countIn(subset: SwebenchSubset): number {
    // Apply the same search filter as `instancesIn(...)` so the chip stays in
    // sync with the per-split chips below it.
    const q = this.instanceSearch.toLowerCase();
    return this.instances.filter(i =>
      i.subset === subset &&
      (!q || i.instance_id.toLowerCase().includes(q) || i.repo.toLowerCase().includes(q))
    ).length;
  }

  isSubsetOpen(s: string): boolean { return this.state.isSubsetOpen(s); }
  toggleSubset(s: string): void { this.state.toggleSubset(s); }
  isSplitOpen(subset: string, split: string): boolean {
    return this.state.isSplitOpen(subset, split);
  }
  toggleSplit(subset: string, split: string): void {
    this.state.toggleSplit(subset, split);
  }

  /** Bulk-select helpers — the ☑/☐ icons in the subset/split headers honor
   * the active filter so users only tick what's actually visible (filtered
   * out instances stay untouched). */
  isSplitAllSelected(subset: SwebenchSubset, split: SwebenchSplit): boolean {
    const leaf = this.instancesIn(subset, split);
    return leaf.length > 0 && leaf.every(i => this.isSelected(i.instance_id));
  }
  toggleSplitSelection(subset: SwebenchSubset, split: SwebenchSplit): void {
    const ids = this.instancesIn(subset, split).map(i => i.instance_id);
    if (ids.length === 0) return;
    const allOn = ids.every(id => this.isSelected(id));
    if (allOn) {
      for (const id of ids) if (this.isSelected(id)) this.toggleInstance(id);
    } else {
      for (const id of ids) if (!this.isSelected(id)) this.toggleInstance(id);
    }
  }
  private subsetLeafIds(subset: SwebenchSubset): string[] {
    const out: string[] = [];
    for (const split of this.splitsFor(subset)) {
      for (const i of this.instancesIn(subset, split)) out.push(i.instance_id);
    }
    return out;
  }
  isSubsetAllSelected(subset: SwebenchSubset): boolean {
    const ids = this.subsetLeafIds(subset);
    return ids.length > 0 && ids.every(id => this.isSelected(id));
  }
  toggleSubsetSelection(subset: SwebenchSubset): void {
    const ids = this.subsetLeafIds(subset);
    if (ids.length === 0) return;
    const allOn = ids.every(id => this.isSelected(id));
    if (allOn) {
      for (const id of ids) if (this.isSelected(id)) this.toggleInstance(id);
    } else {
      for (const id of ids) if (!this.isSelected(id)) this.toggleInstance(id);
    }
  }

  /** Refresh the instances for one (subset, split) leaf. */
  refreshLeaf(subset: SwebenchSubset, split: SwebenchSplit | string): void {
    if (this.refreshing) return;
    this.refreshing = true;
    this.refreshError = '';
    this.cdr.markForCheck();
    this.api.refreshInstances(subset, split as SwebenchSplit).subscribe({
      next: () => { this.refreshing = false; this.loadInstances(); },
      error: err => {
        this.refreshing = false;
        this.refreshError = err?.error?.detail ?? err?.message ?? 'Refresh failed';
        this.cdr.markForCheck();
      },
    });
  }

  /** Refresh every split that the chosen subset ships, sequentially. Uses
   * the same per-leaf endpoint so a partial failure surfaces in
   * `refreshError` without aborting the rest of the splits. */
  refreshSubset(subset: SwebenchSubset): void {
    if (this.refreshing) return;
    const splits = this.splitsFor(subset);
    if (splits.length === 0) return;
    this.refreshing = true;
    this.refreshError = '';
    this.cdr.markForCheck();
    const failures: string[] = [];
    const next = (idx: number) => {
      if (idx >= splits.length) {
        this.refreshing = false;
        this.refreshError = failures.join(' | ');
        this.loadInstances();
        return;
      }
      const split = splits[idx];
      this.api.refreshInstances(subset, split).subscribe({
        next: () => next(idx + 1),
        error: err => {
          failures.push(`${subset}/${split}: ${err?.error?.detail ?? err?.message ?? 'failed'}`);
          next(idx + 1);
        },
      });
    };
    next(0);
  }

  // ─── Lifecycle ──────────────────────────────────────────────────
  ngOnInit(): void {
    // Pull the live-run state from the backend — this restarts the .log
    // polling that ngOnDestroy detached when the user last left the page.
    // No-op on the very first visit (the service's constructor already
    // attached) or when SSE is still streaming for this run.
    this.inferSvc.attach();

    this.loadInstances();
    this.api.getConfigs().subscribe(summaries => {
      // Inference selector still keys off the file stem (the routing key the
      // backend resolves to a JSON file). Display label = id where useful.
      this.configs = summaries.map(s => s.stem);
      if (!this.config && this.configs.length) {
        this.config = this.configs.includes('evo-star') ? 'evo-star' : this.configs[0];
      }
      this.refreshNodeColors();
      this.cdr.markForCheck();
    });

    this.api.getAgentTypes().subscribe(types => {
      this.agentTypes = types;
      this.refreshNodeColors();
    });

    this.changeSub = this.inferSvc.changed.subscribe(() => {
      // Only auto-scroll while the run is in flight AND the user hasn't
      // scrolled up to read history. `stickToBottom` tracks that intent.
      this.shouldScroll = this.inferSvc.running && this.stickToBottom;
      this.cdr.markForCheck();
    });
  }

  /** Re-derive the per-node color map from the active config's agent
   * blocks (each carries a `class` field) looked up against the agent-type
   * catalog. Stored on the run service so the central log panel's chips
   * pick up the right color when their cards are first created. */
  private refreshNodeColors(): void {
    const stem = this.config;
    if (!stem || this.agentTypes.length === 0) return;
    this.api.getConfig(stem).subscribe({
      next: cfg => this.inferSvc.nodeColors = this.buildNodeColors(cfg),
      error: () => this.inferSvc.nodeColors = {},
    });
  }

  private buildNodeColors(cfg: UnifiedConfig): Record<string, string> {
    // Build two lookups off the agent-types catalog so the JSON's `class`
    // field can be either the human-readable AGENT_TYPE label
    // ("Localizator", "Helper/Proxy", …) OR the Python class name
    // ("LocalizatorAgent", "HelperProxyAgent", …) — the backend registers
    // both and the topology JSONs in this repo use the latter.
    const byClass: Record<string, string> = {};
    const byType: Record<string, string> = {};
    for (const t of this.agentTypes) {
      byClass[t.class] = t.color;
      byType[t.type]   = t.color;
    }
    // Hardcoded aliases for the bespoke evo-star Python classes — same
    // table the topology page uses.
    const aliasToType: Record<string, string> = {
      ManagerAgent:    'Planner/Orchestrator',
      LocalizeAgent:   'Localizator',
      PatchAgent:      'Patcher',
      ValidateAgent:   'Reviewer',
      EnsemblerAgent:  'Helper/Proxy',
      LLMToolAgent:    'Base agent',
    };
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

  ngOnDestroy(): void {
    this.changeSub?.unsubscribe();
    // Detach the live SSE / log polling so they don't keep churning the
    // main thread while the user is on Topology / Results / Evaluation.
    // The backend run continues; instance state stays frozen in the
    // service so it's still visible if the user comes back, and ngOnInit
    // calls attach() to resume polling for fresh events.
    this.inferSvc.detach();
  }

  /** True when the log panel is pinned to the bottom edge. Toggled off as
   * soon as the user scrolls up, restored when they scroll back to bottom. */
  stickToBottom = true;

  /** Bound to the scroll panel — toggles `stickToBottom` based on whether
   * the user is sitting at the bottom (16px tolerance for browsers that
   * round subpixel scroll positions). */
  onLogScroll(): void {
    if (!this.scrollEl) return;
    const el = this.scrollEl.nativeElement;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    this.stickToBottom = distanceFromBottom < 16;
  }

  ngAfterViewChecked(): void {
    if (this.shouldScroll && this.scrollEl) {
      const el = this.scrollEl.nativeElement;
      el.scrollTop = el.scrollHeight;
      this.shouldScroll = false;
    }
  }

  // ─── Instances ─────────────────────────────────────────────────
  loadInstances(): void {
    this.loadingInstances = true;
    const skip = this.instancesPage * this.instancesPageSize;
    this.api.getInstances(skip, this.instancesPageSize).subscribe(list => {
      this.instances = list;
      this.filterInstances();
      this.loadingInstances = false;
      this.cdr.markForCheck();
      this.api.countInstances().subscribe(r => {
        this.instancesTotal = r.count;
        this.cdr.markForCheck();
      });
    });
  }

  /** Top-level "↻" button — refreshes EVERY (subset, split) pair the dataset
   * ships. Heavy: Full alone is ~2000 instances per split. Per-leaf `↻` buttons
   * inside each split header refresh just that pair if you want a quick pull. */
  refreshInstances(): void {
    if (this.refreshing) return;
    this.refreshing = true;
    this.refreshError = '';
    this.cdr.markForCheck();
    this.api.refreshAllInstances().subscribe({
      next: (res) => {
        this.refreshing = false;
        // Surface any per-combo errors so the user sees what couldn't be pulled.
        const failures = Object.entries(res.results)
          .filter(([, v]) => 'error' in v)
          .map(([k, v]) => `${k}: ${v.error}`);
        if (failures.length) this.refreshError = failures.join(' | ');
        this.loadInstances();
      },
      error: err => {
        this.refreshing = false;
        this.refreshError = err?.error?.detail ?? err?.message ?? 'Refresh failed';
        this.cdr.markForCheck();
      },
    });
  }

  filterInstances(): void {
    // `filteredInstances` is the flat union shown by the search filter — used
    // by `selectAllVisible()`. The grouped view filters via `instancesIn()`.
    const q = this.instanceSearch.toLowerCase();
    this.filteredInstances = !q
      ? this.instances
      : this.instances.filter(
          i =>
            i.instance_id.toLowerCase().includes(q) ||
            i.repo.toLowerCase().includes(q),
        );
  }

  selectAllVisible(): void {
    // Limit "Select visible" to what's actually unfolded in the grouped panel
    // so an accidental click doesn't tick a thousand collapsed Full instances.
    const visible: string[] = [];
    for (const subset of this.subsets) {
      if (!this.isSubsetOpen(subset)) continue;
      for (const split of this.splitsFor(subset)) {
        if (!this.isSplitOpen(subset, split)) continue;
        for (const i of this.instancesIn(subset, split)) visible.push(i.instance_id);
      }
    }
    this.state.setSelection([...this.state.selectedList, ...visible]);
  }

  // ─── Run / Cancel ──────────────────────────────────────────────
  run(): void {
    const ids = this.state.selectedList;
    if (ids.length === 0 || this.running) return;
    this.inferSvc.run(ids, this.config);
    this.state.clearSelection();
  }

  cancel(): void {
    this.inferSvc.cancel();
  }

  // ─── Helpers ────────────────────────────────────────────────────
  toggleCard(card: AgentCard): void {
    card.expanded = !card.expanded;
  }

  private readonly THINKING_KEYS = new Set(['thinking', 'think', 'thought', 'thoughts', 'reasoning']);

  formatDelta(delta: Record<string, unknown>): { key: string; value: string; type: string; isThinking: boolean }[] {
    return Object.entries(delta)
      .filter(([k]) => !['workspace_path', 'issue_text', 'instance', 'thinking'].includes(k))
      .map(([key, value]) => {
        let type = 'text';
        let str = '';
        if (key === 'final_patch' || key === 'candidate_patches') {
          type = 'code';
          str = Array.isArray(value) ? value.join('\n\n─────\n\n') : String(value ?? '');
        } else if (key === 'validation_results' && Array.isArray(value)) {
          type = 'json';
          str = JSON.stringify(value, null, 2);
        } else if (Array.isArray(value)) {
          str = (value as unknown[]).join('\n');
        } else {
          str = String(value ?? '');
        }
        return { key, value: str, type, isThinking: this.THINKING_KEYS.has(key) };
      });
  }

  formatDiff(patch: string): { line: string; cls: string }[] {
    return patch.split('\n').map(line => {
      let cls = '';
      if (line.startsWith('+') && !line.startsWith('+++')) cls = 'diff-add';
      else if (line.startsWith('-') && !line.startsWith('---')) cls = 'diff-rm';
      else if (line.startsWith('@@') || line.startsWith('diff ')) cls = 'diff-hdr';
      return { line, cls };
    });
  }

  trackByAgent(_: number, c: AgentCard): string { return c.agent; }
}
