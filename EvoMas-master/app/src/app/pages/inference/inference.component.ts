/** Inference page shell. Owns cross-cutting state (instance list,
 * refresh status, agent-types catalog, custom-repo form) and composes
 * four sub-components plus the shared `<app-inference-instance-view>`
 * stream area. Sub-components project slices via @Input; intents bubble
 * back via @Output and translate into `InferenceRunService` /
 * `InferenceStateService` calls here. */
import {
  AfterViewChecked, ChangeDetectorRef, Component, ElementRef,
  OnDestroy, OnInit, ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subscription } from 'rxjs';

import { ApiService } from '../../services/api.service';
import {
  InferenceRunService, RunInstance, buildNodeColors,
} from '../../services/inference-run.service';
import { InferenceStateService } from '../../services/inference-state.service';
import {
  AgentType, Instance, SwebenchSubset, SwebenchSplit,
} from '../../models/types';
import { InferenceInstanceViewComponent } from '../../components/index';
import {
  InstancePickerTreeComponent, RunControlsBarComponent,
  BatchProgressStripComponent, CustomRepoModalComponent,
} from './components/index';

@Component({
  selector: 'app-inference',
  standalone: true,
  imports: [
    CommonModule, InferenceInstanceViewComponent,
    InstancePickerTreeComponent, RunControlsBarComponent,
    BatchProgressStripComponent, CustomRepoModalComponent,
  ],
  templateUrl: './inference.component.html',
  styleUrl: './inference.component.css',
})
export class InferenceComponent implements OnInit, OnDestroy, AfterViewChecked {
  @ViewChild('scrollEl') scrollEl!: ElementRef<HTMLDivElement>;

  // ─── Instances ─────────────────────────────────────────────────
  instances: Instance[] = [];
  instancesTotal = 0;
  /** 0 = unlimited. The grouped picker handles thousands of rows fine since
   * each subset/split expander is collapsed by default. */
  instancesPageSize = 0;
  loadingInstances = false;
  refreshing = false;
  refreshError = '';

  configs: string[] = [];
  showThinking = true;
  /** Live catalog from /api/agent-types — drives the per-node color map
   * the central log panel renders chips with. */
  private agentTypes: AgentType[] = [];
  private changeSub?: Subscription;
  shouldScroll = false;
  /** True when the log panel is pinned to the bottom edge. */
  stickToBottom = true;

  // ─── Custom-repo modal state ──────────────────────────────────
  customFormOpen = false;
  customRepo = '';
  customProblem = '';
  customBaseCommit = '';
  customSubmitting = false;
  customError = '';

  constructor(
    private api: ApiService,
    public inferSvc: InferenceRunService,
    public state: InferenceStateService,
    private cdr: ChangeDetectorRef,
  ) {}

  // ─── Getters delegating to the run service ─────────────────────
  get running(): boolean { return this.inferSvc.running; }
  get cancelled(): boolean { return this.inferSvc.cancelled; }
  get statusMsg(): string { return this.inferSvc.statusMsg; }
  get runInstances(): RunInstance[] { return this.inferSvc.instances; }
  get currentInstance(): RunInstance | null { return this.inferSvc.currentInstance; }

  selectInstanceInRun(id: string): void { this.inferSvc.selectInstance(id); }
  clearRun(): void { this.inferSvc.clear(); }

  // ─── State service proxies ─────────────────────────────────────
  get selectionCount(): number { return this.state.selectedInstanceIds.size; }
  get firstSelected(): string { return this.state.selectedList[0] ?? ''; }
  get instanceSearch(): string { return this.state.instanceSearch; }
  set instanceSearch(v: string) { this.state.instanceSearch = v; }
  get config(): string { return this.state.config; }
  setConfig(v: string): void {
    const changed = this.state.config !== v;
    this.state.config = v;
    if (changed) this.refreshNodeColors();
  }

  // ─── Lifecycle ─────────────────────────────────────────────────
  ngOnInit(): void {
    this.inferSvc.attach();
    this.loadInstances();
    this.api.getConfigs().subscribe(summaries => {
      this.configs = summaries.map(s => s.stem);
      if (!this.config && this.configs.length) {
        this.setConfig(this.configs.includes('chain') ? 'chain' : this.configs[0]);
      }
      this.refreshNodeColors();
      this.cdr.markForCheck();
    });
    this.api.getAgentTypes().subscribe(types => {
      this.agentTypes = types;
      this.refreshNodeColors();
    });
    this.changeSub = this.inferSvc.changed.subscribe(() => {
      this.shouldScroll = this.inferSvc.running && this.stickToBottom;
      this.cdr.markForCheck();
    });
  }

  private refreshNodeColors(): void {
    const stem = this.config;
    if (!stem || this.agentTypes.length === 0) return;
    this.api.getConfig(stem).subscribe({
      next: cfg => this.inferSvc.nodeColors = buildNodeColors(cfg, this.agentTypes),
      error: () => this.inferSvc.nodeColors = {},
    });
  }

  ngOnDestroy(): void {
    this.changeSub?.unsubscribe();
    this.inferSvc.detach();
  }

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

  // ─── Instance picker outputs ───────────────────────────────────
  loadInstances(): void {
    this.loadingInstances = true;
    const skip = this.state.instancesPage * this.instancesPageSize;
    this.api.getInstances(skip, this.instancesPageSize).subscribe(list => {
      this.instances = list;
      this.loadingInstances = false;
      this.cdr.markForCheck();
      this.api.countInstances().subscribe(r => {
        this.instancesTotal = r.count;
        this.cdr.markForCheck();
      });
    });
  }

  refreshAll(): void {
    if (this.refreshing) return;
    this.refreshing = true;
    this.refreshError = '';
    this.cdr.markForCheck();
    this.api.refreshAllInstances().subscribe({
      next: res => {
        this.refreshing = false;
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

  refreshLeaf(payload: { subset: SwebenchSubset; split: SwebenchSplit }): void {
    if (this.refreshing) return;
    if (payload.subset === 'custom') return;
    this.refreshing = true;
    this.refreshError = '';
    this.cdr.markForCheck();
    this.api.refreshInstances(payload.subset, payload.split as 'dev' | 'test' | 'train').subscribe({
      next: () => { this.refreshing = false; this.loadInstances(); },
      error: err => {
        this.refreshing = false;
        this.refreshError = err?.error?.detail ?? err?.message ?? 'Refresh failed';
        this.cdr.markForCheck();
      },
    });
  }

  refreshSubset(subset: SwebenchSubset): void {
    if (this.refreshing || subset === 'custom') return;
    const splits: SwebenchSplit[] = ['dev', 'test', 'train'].filter(
      // narrow to splits this subset ships; same logic as in SUBSET_SPLITS
      sp => true,
    ) as SwebenchSplit[];
    // Delegate to the per-leaf refresh, sequentially:
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
      this.api.refreshInstances(subset, split as 'dev' | 'test' | 'train').subscribe({
        next: () => next(idx + 1),
        error: err => {
          failures.push(`${subset}/${split}: ${err?.error?.detail ?? err?.message ?? 'failed'}`);
          next(idx + 1);
        },
      });
    };
    next(0);
  }

  toggleSplitSelection(payload: { subset: SwebenchSubset; split: SwebenchSplit }): void {
    // Use the picker's filter via the page's own search state; rebuild ids list
    // from cached instances + active filter so we honor what's actually visible.
    const q = this.state.instanceSearch.toLowerCase();
    const ids = this.instances
      .filter(i => i.subset === payload.subset && i.split === payload.split &&
                   (!q || i.instance_id.toLowerCase().includes(q) || i.repo.toLowerCase().includes(q)))
      .map(i => i.instance_id);
    if (ids.length === 0) return;
    const allOn = ids.every(id => this.state.isSelected(id));
    for (const id of ids) {
      const on = this.state.isSelected(id);
      if (allOn && on) this.state.toggleInstance(id);
      if (!allOn && !on) this.state.toggleInstance(id);
    }
  }

  toggleSubsetSelection(subset: SwebenchSubset): void {
    const q = this.state.instanceSearch.toLowerCase();
    const ids = this.instances
      .filter(i => i.subset === subset &&
                   (!q || i.instance_id.toLowerCase().includes(q) || i.repo.toLowerCase().includes(q)))
      .map(i => i.instance_id);
    if (ids.length === 0) return;
    const allOn = ids.every(id => this.state.isSelected(id));
    for (const id of ids) {
      const on = this.state.isSelected(id);
      if (allOn && on) this.state.toggleInstance(id);
      if (!allOn && !on) this.state.toggleInstance(id);
    }
  }

  selectAllVisible(): void {
    const q = this.state.instanceSearch.toLowerCase();
    const visible: string[] = [];
    for (const inst of this.instances) {
      if (q && !inst.instance_id.toLowerCase().includes(q) && !inst.repo.toLowerCase().includes(q)) continue;
      // Only ids whose subset+split expander is open
      if (this.state.isSubsetOpen(inst.subset) && this.state.isSplitOpen(inst.subset, inst.split)) {
        visible.push(inst.instance_id);
      }
    }
    this.state.setSelection([...this.state.selectedList, ...visible]);
  }

  // ─── Run / cancel ──────────────────────────────────────────────
  run(): void {
    const ids = this.state.selectedList;
    if (ids.length === 0 || this.running) return;
    this.inferSvc.run(ids, this.config);
    this.state.clearSelection();
  }
  cancel(): void { this.inferSvc.cancel(); }

  // ─── Custom-repo modal handlers ────────────────────────────────
  toggleCustomForm(): void {
    this.customFormOpen = !this.customFormOpen;
    if (!this.customFormOpen) this.customError = '';
  }

  submitCustomInstance(): void {
    const repo = this.customRepo.trim();
    const problem = this.customProblem.trim();
    if (!repo || !problem || this.customSubmitting) return;
    this.customSubmitting = true;
    this.customError = '';
    this.cdr.markForCheck();
    this.api.addCustomInstance(repo, problem, this.customBaseCommit.trim() || undefined).subscribe({
      next: res => {
        this.customSubmitting = false;
        this.api.getInstances(0, this.instancesPageSize).subscribe(list => {
          this.instances = list;
          this.api.countInstances().subscribe(r => {
            this.instancesTotal = r.count;
            this.cdr.markForCheck();
          });
          if (!this.state.isSelected(res.instance_id)) this.state.toggleInstance(res.instance_id);
          if (!this.state.isSubsetOpen('custom')) this.state.toggleSubset('custom');
          if (!this.state.isSplitOpen('custom', 'custom')) this.state.toggleSplit('custom', 'custom');
          this.cdr.markForCheck();
        });
        this.customRepo = '';
        this.customProblem = '';
        this.customBaseCommit = '';
        this.customFormOpen = false;
        this.cdr.markForCheck();
      },
      error: err => {
        this.customSubmitting = false;
        this.customError = err?.error?.detail ?? err?.message ?? 'Failed to add custom instance';
        this.cdr.markForCheck();
      },
    });
  }
}
