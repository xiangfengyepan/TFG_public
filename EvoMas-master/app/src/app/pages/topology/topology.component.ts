import {
  Component, OnInit, OnDestroy, AfterViewInit, HostListener,
  ElementRef, ViewChild, ChangeDetectorRef, NgZone, signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import cytoscape, { Core, NodeSingular, EdgeSingular } from 'cytoscape';
import { ApiService } from '../../services/api.service';
import { TopologyStateService } from '../../services/topology-state.service';
import {
  AgentBlock, AgentTool, AgentType, AgentVariant, ConfigSummary, ToolDescriptor, UnifiedConfig,
  AGENT_COLORS, AGENT_LABELS, ALL_AGENTS, normalizeNodeBase, suggestNodeId,
} from '../../models/types';
import { SelectOption, SelectOptionGroup } from '../../components/select/evo-select.component';
import { findAllCycles } from '../../utils/cycles';
import {
  ConfigHistoryPanelComponent,
  ConfigListPanelComponent,
  TopologyToolbarComponent,
  AgentInspectorComponent,
  TopologyPaletteComponent,
} from './components/index';

/** Owner for tools without a `repo` field. */
const FALLBACK_REPO = 'evomas';

/** Pin `evomas` first in the "Add tool" dropdown; the rest alphabetical. */
const REPO_GROUP_ORDER: readonly string[] = ['evomas'];

/** Virtual flow-boundary node ids; never appear in the serialized config. */
const START_NODE_ID = '__START__';
const END_NODE_ID   = '__END__';

@Component({
  selector: 'app-topology',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    ConfigHistoryPanelComponent,
    ConfigListPanelComponent,
    TopologyToolbarComponent,
    AgentInspectorComponent,
    TopologyPaletteComponent,
  ],
  templateUrl: './topology.component.html',
  styleUrl: './topology.component.css',
})
export class TopologyComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('graphEl') graphEl!: ElementRef<HTMLDivElement>;

  private cy!: Core;
  edgeSource: string | null = null;

  readonly allAgents = ALL_AGENTS;
  readonly agentColors = AGENT_COLORS;
  readonly agentLabels = AGENT_LABELS;

  private configChangedSub?: Subscription;

  historyPanelOpen = false;

  /** Pretty-printed JSON of the current in-memory config; `null` = no config. */
  get currentConfigJson(): string | null {
    const cfg = this.currentConfig;
    if (!cfg) return null;
    try {
      return JSON.stringify(cfg, null, 2);
    } catch {
      return null;
    }
  }

  constructor(
    private api: ApiService,
    private svc: TopologyStateService,
    private cdr: ChangeDetectorRef,
    private zone: NgZone,
  ) {}

  // ─── Proxies into TopologyStateService ────────────────────────
  get predefinedConfigs(): ConfigSummary[] { return this.svc.predefinedConfigs; }
  set predefinedConfigs(v: ConfigSummary[]) { this.svc.predefinedConfigs = v; }

  get currentConfig(): UnifiedConfig | null { return this.svc.currentConfig; }
  get currentConfigName(): string | null { return this.svc.currentConfigName; }

  get selectedAgent(): string | null { return this.svc.selectedAgent; }
  set selectedAgent(v: string | null) { this.svc.selectedAgent = v; }
  get selectedEdgeId(): string | null { return this.svc.selectedEdgeId; }
  set selectedEdgeId(v: string | null) { this.svc.selectedEdgeId = v; }

  get modelSelectOptions(): SelectOption[] { return this.svc.modelSelectOptions; }
  set modelSelectOptions(v: SelectOption[]) { this.svc.modelSelectOptions = v; }

  get addEdgeMode(): boolean { return this.svc.addEdgeMode; }
  set addEdgeMode(v: boolean) { this.svc.addEdgeMode = v; }

  /** Unsaved-in-memory edits — drives the toolbar "unsaved" chip. */
  get dirty(): boolean { return this.svc.dirty; }
  /** Validated since the last edit — gates the Save button. */
  get validated(): boolean { return this.svc.validated; }
  /** Flag the config dirty + unvalidated. Call after every mutation. */
  private markDirty(): void {
    if (this.svc.dirty && !this.svc.validated) return;
    this.svc.dirty = true;
    this.svc.validated = false;
    this.cdr.markForCheck();
  }

  get agentBlock(): AgentBlock | null { return this.svc.selectedAgentBlock(); }

  availableTools: ToolDescriptor[] = [];
  agentTypes: AgentType[] = [];
  /** type label → color */
  private typeColor: Record<string, string> = {};
  /** Python class name or type label → canonical type label. */
  private classToType: Record<string, string> = {};

  // Variant dropdown selection per AGENT_TYPE (persisted via state).
  // Variants enumeration + default-key selection lives in the palette
  // sub-component; this component only persists the current pick.
  get selectedVariantByType(): Record<string, string> {
    return this.svc.selectedVariantByType;
  }
  onVariantChange(type: string, key: string): void {
    this.selectedVariantByType[type] = key;
    this.cdr.markForCheck();
  }
  /** Find a variant by key across all types; null when unknown. */
  private findVariant(key: string): AgentVariant | null {
    for (const t of this.agentTypes) {
      const hit = (t.variants ?? []).find(v => v.key === key);
      if (hit) return hit;
    }
    return null;
  }

  // ─── Lifecycle ─────────────────────────────────────────────────
  ngOnInit(): void {
    this.api.getModels().subscribe({
      next: models => {
        this.svc.availableModels = models;
        this.syncModelOptions(this.agentBlock?.model ?? '');
        this.cdr.markForCheck();
      },
      error: () => { this.svc.availableModels = []; },
    });

    this.api.getTools().subscribe({
      next: tools => { this.availableTools = tools; this.cdr.markForCheck(); },
      error: () => { this.availableTools = []; },
    });

    this.api.getAgentTypes().subscribe({
      next: types => {
        this.agentTypes = types;
        this.typeColor = Object.fromEntries(types.map(t => [t.type, t.color]));
        // class → type label, keyed by Python class AND type label so both
        // shapes ("LocatorAgent", "Locator") resolve to a colored type.
        const map: Record<string, string> = {};
        for (const t of types) {
          map[t.class] = t.type;
          map[t.type]  = t.type;
        }
        map['LLMToolAgent'] = 'Base agent';
        this.classToType = map;
        if (this.currentConfig) this.renderConfig(this.currentConfig);
        this.cdr.markForCheck();
      },
      error: () => { this.agentTypes = []; },
    });

    this.api.getConfigs().subscribe(summaries => {
      this.predefinedConfigs = summaries;
      this.cdr.detectChanges();
      if (!this.currentConfig && summaries.length > 0) {
        const chain = summaries.find(s => s.stem === 'chain');
        this.loadPredefined((chain ?? summaries[0]).stem);
      }
    });

    // Re-render when the config is replaced via the navbar Open dropdown.
    this.configChangedSub = this.svc.configChanged.subscribe(cfg => {
      if (cfg) {
        this.zone.run(() => {
          this.renderConfig(cfg);
          this.syncModelOptions(this.agentBlock?.model ?? '');
          this.cdr.markForCheck();
        });
      }
    });

    this.reloadGraph();
    this.installBeforeUnload();
  }

  ngAfterViewInit(): void {
    this.initCytoscape([]);
    if (this.currentConfig) {
      this.renderConfig(this.currentConfig);
    }
  }

  ngOnDestroy(): void {
    this.saveNodePositions();
    this.configChangedSub?.unsubscribe();
    if (this.beforeUnloadHandler) {
      window.removeEventListener('beforeunload', this.beforeUnloadHandler);
    }
    this.cy?.destroy();
  }

  private beforeUnloadHandler?: (e: BeforeUnloadEvent) => void;

  /** Browser tab-close prompt for unsaved edits. */
  private installBeforeUnload(): void {
    if (this.beforeUnloadHandler) return;
    this.beforeUnloadHandler = (e: BeforeUnloadEvent) => {
      if (this.svc.dirty && this.isLoadedConfig) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', this.beforeUnloadHandler);
  }

  private saveNodePositions(): void {
    const key = this.currentConfigName;
    if (!this.cy || !key) return;
    const positions: Record<string, { x: number; y: number }> = {};
    this.cy.nodes().forEach((n: NodeSingular) => {
      // Skip virtual boundary nodes; they're layout-derived.
      const id = n.id();
      if (id === START_NODE_ID || id === END_NODE_ID) return;
      const p = n.position();
      positions[id] = { x: p.x, y: p.y };
    });
    this.svc.nodePositions[key] = positions;
  }

  // ─── Helpers ───────────────────────────────────────────────────
  baseAgentId(id: string): string {
    return id.replace(/_\d+$/, '');
  }

  /** Human-readable label, falling back to the raw node id. */
  labelOrId(id: string): string {
    const base = this.baseAgentId(id);
    const labels = this.agentLabels as Record<string, string | undefined>;
    return labels[base] ?? id;
  }

  isPredefined(stem: string): boolean {
    return this.predefinedConfigs.some(c => c.stem === stem && c.source !== 'loaded');
  }

  get predefinedList(): ConfigSummary[] {
    return this.predefinedConfigs.filter(c => c.source !== 'loaded');
  }

  get loadedList(): ConfigSummary[] {
    return this.predefinedConfigs.filter(c => c.source === 'loaded');
  }

  /** Double-click rename for loaded configs (predefined are read-only). */
  renameLoaded(stem: string): void {
    if (this.isPredefined(stem)) return;
    const proposed = window.prompt('Rename config to:', stem);
    if (!proposed) return;
    const trimmed = proposed.trim();
    if (!trimmed || trimmed === stem) return;
    if (/[\\/:*?"<>|\s]/.test(trimmed)) {
      window.alert('Name contains invalid characters.');
      return;
    }
    this.api.renameLoadedConfig(stem, trimmed).subscribe({
      next: () => {
        this.api.getConfigs().subscribe(list => {
          this.predefinedConfigs = list;
          if (this.currentConfigName === stem) {
            this.loadPredefined(trimmed);
          }
          this.cdr.markForCheck();
        });
      },
      error: err => {
        window.alert(`Rename failed: ${err?.error?.detail ?? err?.message ?? 'unknown error'}`);
      },
    });
  }

  /** Delete a loaded config from disk. Prompts for confirmation. */
  deleteLoaded(stem: string, ev?: Event): void {
    ev?.stopPropagation();
    if (this.isPredefined(stem)) return;
    if (!window.confirm(`Delete loaded config "${stem}"? This removes the file from evomas/config/loaded/.`)) return;
    this.api.deleteLoadedConfig(stem).subscribe({
      next: () => {
        this.api.getConfigs().subscribe(list => {
          this.predefinedConfigs = list;
          if (this.currentConfigName === stem) {
            const next = this.predefinedList[0];
            if (next) this.loadPredefined(next.stem);
          }
          this.cdr.markForCheck();
        });
      },
      error: err => {
        window.alert(`Delete failed: ${err?.error?.detail ?? err?.message ?? 'unknown error'}`);
      },
    });
  }

  /** Substring-insensitive filter for the model dropdown. */
  modelFilter = '';

  // ─── Topology stats (top-panel) ─────────────────────────────────
  get agentCount(): number {
    return this.currentConfig ? Object.keys(this.currentConfig.agents).length : 0;
  }

  get edgeCount(): number {
    return this.currentConfig?.edges?.length ?? 0;
  }

  /** Distinct simple cycles via Johnson's algorithm. */
  get cycleCount(): number {
    if (!this.currentConfig) return 0;
    const nodes = Object.keys(this.currentConfig.agents);
    const edges: [string, string][] =
      (this.currentConfig.edges ?? []).map(e => [e.from, e.to]);
    return findAllCycles(nodes, edges).length;
  }

  get isDag(): boolean { return this.cycleCount === 0; }

  get topoStatsTooltip(): string {
    const a = this.agentCount;
    const e = this.edgeCount;
    const c = this.cycleCount;
    return `${a} agent${a === 1 ? '' : 's'}, ${e} edge${e === 1 ? '' : 's'}, `
      + `${c} simple cycle${c === 1 ? '' : 's'} (${this.isDag ? 'DAG — topological order exists' : 'cycles allowed at runtime — capped by EVOMAS_GRAPH_MAX_REVISITS'})`;
  }

  /** Build model dropdown options. Current model is always present and
   * bypasses the filter; unpulled entries get a `· pull` label suffix. */
  private syncModelOptions(model: string): void {
    const filter = this.modelFilter.trim().toLowerCase();
    const known = new Set(this.svc.availableModels.map(m => m.name));
    const items: SelectOption[] = [];

    // Synthetic entry for an active model not in the catalog/tags.
    if (model && !known.has(model)) {
      items.push({ value: model, label: `${model}  ·  custom` });
    }
    for (const m of this.svc.availableModels) {
      const label = m.pulled ? m.name : `${m.name}  ·  pull`;
      // Active model is always shown regardless of filter.
      const passesFilter =
        m.name === model ||
        !filter ||
        m.name.toLowerCase().includes(filter);
      if (passesFilter) items.push({ value: m.name, label });
    }
    this.modelSelectOptions = items;
  }

  onModelFilterChange(value: string): void {
    this.modelFilter = value;
    this.syncModelOptions(this.agentBlock?.model ?? '');
    this.cdr.markForCheck();
  }

  /** `custom` when the model isn't in /api/tags AND not in the catalog. */
  get currentModelStatus(): 'pulled' | 'unpulled' | 'custom' {
    const model = this.agentBlock?.model ?? '';
    if (!model) return 'custom';
    const found = this.svc.availableModels.find(m => m.name === model);
    if (!found) return 'custom';
    return found.pulled ? 'pulled' : 'unpulled';
  }

  /** Unprefixed legacy values default to `ollama` (matches `parse_provider`). */
  providerOf(model: string | undefined | null): 'ollama' | 'gemini' | 'openai' {
    const m = (model ?? '').trim().toLowerCase();
    if (m.startsWith('gemini/')) return 'gemini';
    if (m.startsWith('openai/')) return 'openai';
    return 'ollama';
  }

  /** Whether the current provider honors `knob` — mirrors `evomas/models/`. */
  supportsKnob(knob: string): boolean {
    const p = this.providerOf(this.agentBlock?.model);
    if (p === 'ollama') return true;
    if (p === 'gemini') {
      return ['temperature', 'top_p', 'top_k', 'num_predict', 'stream', 'model'].includes(knob);
    }
    // openai
    return ['temperature', 'top_p', 'num_predict', 'seed', 'stream', 'model'].includes(knob);
  }

  loadError = '';

  // ─── Load predefined config ────────────────────────────────────
  loadPredefined(name: string): void {
    this.api.getConfig(name).subscribe({
      next: cfg => {
        this.loadError = '';
        this.svc.setCurrentConfig(cfg, name);
        this.renderConfig(cfg);
        this.cdr.markForCheck();
      },
      error: err => {
        // Drop the previous topology so the failed click clears the canvas.
        this.svc.setCurrentConfig(null, name);
        this.cy?.elements().remove();
        const detail = err?.error?.detail ?? err?.message ?? 'unknown error';
        this.loadError = `Failed to load "${name}": ${detail}`;
        this.cdr.markForCheck();
      },
    });
  }

  // ─── Cytoscape init & render ───────────────────────────────────
  private initCytoscape(elements: cytoscape.ElementDefinition[], skipLayout = false): void {
    if (!this.graphEl) return;
    this.cy?.destroy();

    this.cy = cytoscape({
      container: this.graphEl.nativeElement,
      elements,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'background-color': 'data(color)',
            color: '#0d1117',
            'text-valign': 'center',
            'text-halign': 'center',
            'font-size': 11,
            'font-weight': 'bold',
            // Auto-size to label so long ids don't overflow.
            width: 'label',
            'padding-left':  '14px',
            'padding-right': '14px',
            'padding-top':   '8px',
            'padding-bottom':'8px',
            'min-width':     80,
            shape: 'round-rectangle',
            'border-width': 2,
            'border-color': 'transparent',
          } as any,
        },
        {
          selector: 'node:selected',
          style: { 'border-color': '#fff', 'border-width': 3 } as any,
        },
        {
          selector: 'node.edge-source',
          style: { 'border-color': '#f0e040', 'border-width': 3 } as any,
        },
        {
          selector: 'edge',
          style: {
            width: 2,
            'line-color': '#30363d',
            'target-arrow-color': '#30363d',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'arrow-scale': 1.4,
          } as any,
        },
        {
          selector: 'edge:selected',
          style: { 'line-color': '#f85149', 'target-arrow-color': '#f85149', width: 3 } as any,
        },
        // Conditional edge: Orchestrator + ≥2 out-edges → LLM-driven router.
        {
          selector: 'edge.edge-conditional',
          style: {
            'line-color': '#a371f7',
            'target-arrow-color': '#a371f7',
            'line-style': 'dashed',
            'line-dash-pattern': [6, 4],
            width: 2.2,
          } as any,
        },
        // Back-edge: amber arc; signed `cpd` keeps the curve on the
        // outside of the forward layout as endpoints move.
        {
          selector: 'edge.edge-loopback',
          style: {
            'line-color': '#e3b341',
            'target-arrow-color': '#e3b341',
            'curve-style': 'unbundled-bezier',
            'control-point-distances': 'data(cpd)' as any,
            'control-point-weights': [0.5],
            width: 2.2,
          } as any,
        },
        // Selection: preserve dashed/curve traits while flipping color.
        {
          selector: 'edge.edge-conditional:selected, edge.edge-loopback:selected',
          style: { 'line-color': '#f85149', 'target-arrow-color': '#f85149', width: 3 } as any,
        },
        // Virtual START / END pills — dashed grey so they read as control flow.
        {
          selector: 'node.virtual-node',
          style: {
            'background-color': '#21262d',
            color: '#c9d1d9',
            shape: 'round-rectangle',
            'border-width': 2,
            'border-color': '#6e7681',
            'border-style': 'dashed',
            label: 'data(label)',
            width: 'label',
            'min-width': 56,
            'padding-left': '12px',
            'padding-right': '12px',
            'padding-top': '6px',
            'padding-bottom': '6px',
            'font-size': 11,
            'font-weight': 'bold',
            'text-valign': 'center',
            'text-halign': 'center',
          } as any,
        },
        // Virtual edges: dashed thin grey.
        {
          selector: 'edge.virtual-edge',
          style: {
            width: 1.5,
            'line-color': '#6e7681',
            'target-arrow-color': '#6e7681',
            'line-style': 'dashed',
          } as any,
        },
        {
          selector: 'edge.virtual-edge:selected',
          style: {
            'line-color': '#f85149',
            'target-arrow-color': '#f85149',
            width: 2.5,
          } as any,
        },
      ],
      layout: skipLayout
        ? { name: 'preset' }
        : {
            name: 'breadthfirst', directed: true, padding: 40, spacingFactor: 1.2,
            nodeDimensionsIncludeLabels: true,
            // Horizontal flow: swap x↔y so BFS lays out LTR.
            transform: (_node: any, pos: any) => ({ x: pos.y, y: pos.x }),
          } as any,
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
      // Clamp zoom so `cy.fit()` keeps labels readable on large graphs.
      minZoom: 0.65,
      maxZoom: 2.5,
    });

    this.cy.on('tap', 'node', evt => this.zone.run(() => this.onNodeTap(evt.target)));
    this.cy.on('tap', 'edge', evt => this.zone.run(() => this.onEdgeTap(evt.target)));
    this.cy.on('tap', evt => {
      if (evt.target === (this.cy as any)) {
        this.zone.run(() => {
          this.selectedAgent = null;
          this.selectedEdgeId = null;
          if (this.addEdgeMode && this.edgeSource) {
            this.cy.getElementById(this.edgeSource).removeClass('edge-source');
            this.edgeSource = null;
          }
        });
      }
    });
    this.cy.on('dragfreeon', 'node', () => this.zone.run(() => this.saveNodePositions()));

    // One handler keeps the starfield, world-grid, and zoom% readout in sync.
    const onView = () => this.zone.run(() => this.syncCyView());
    this.cy.on('pan', onView);
    this.cy.on('zoom', onView);
    this.cy.on('resize', onView);
    this.syncCyView();

    // Live-track loop-back arc direction as endpoints move.
    this.cy.on('position', 'node', evt => this.refreshLoopbackCurves(evt.target));
  }

  /** Sign `cpd` per loop-back edge so the arc bulges opposite to the
   * forward-flow band — flips when an endpoint crosses the other. */
  private refreshLoopbackCurves(movedNode?: any): void {
    if (!this.cy) return;
    const magnitude = 70;
    const edges = movedNode
      ? movedNode.connectedEdges('.edge-loopback')
      : this.cy.edges('.edge-loopback');
    edges.forEach((e: any) => {
      const src = e.source().position();
      const tgt = e.target().position();
      const sign = tgt.y < src.y ? -1 : 1;
      e.data('cpd', [sign * magnitude]);
    });
  }

  /** DFS back-edge detection — set of `from-to` ids that close a cycle. */
  private findBackEdges(cfg: UnifiedConfig): Set<string> {
    const adj: Record<string, string[]> = {};
    for (const e of cfg.edges) (adj[e.from] = adj[e.from] || []).push(e.to);
    const back = new Set<string>();
    const onStack = new Set<string>();
    const visited = new Set<string>();
    const dfs = (node: string): void => {
      visited.add(node);
      onStack.add(node);
      for (const next of (adj[node] || [])) {
        if (onStack.has(next)) {
          back.add(`${node}-${next}`);
        } else if (!visited.has(next)) {
          dfs(next);
        }
      }
      onStack.delete(node);
    };
    if (cfg.entry && cfg.agents[cfg.entry]) dfs(cfg.entry);
    // Cover disconnected sub-graphs as new DFS roots.
    for (const id of Object.keys(cfg.agents)) {
      if (!visited.has(id)) dfs(id);
    }
    return back;
  }

  /** Conditional = Orchestrator source with ≥2 out-edges (matches `_make_router`). */
  private isConditionalEdge(
    edge: { from: string; to: string },
    cfg: UnifiedConfig,
    outDegree: Record<string, number>,
  ): boolean {
    if ((outDegree[edge.from] ?? 0) < 2) return false;
    return cfg.agents[edge.from]?.class === 'Orchestrator';
  }

  /** Normalize `cfg.end` (string | string[]) into a flat id array. */
  private endNodeIds(cfg: UnifiedConfig): string[] {
    if (typeof cfg.end === 'string') return cfg.end ? [cfg.end] : [];
    if (Array.isArray(cfg.end)) return cfg.end.filter(Boolean);
    return [];
  }

  private renderConfig(cfg: UnifiedConfig): void {
    const key = this.currentConfigName ?? cfg.id;
    const savedPos = this.svc.nodePositions[key] ?? {};
    const hasPositions = Object.keys(savedPos).length > 0;

    const nodeIds = Object.keys(cfg.agents);
    // Drop dangling-edge references; Cytoscape rolls back the whole batch
    // if any edge points at a missing node. Bad edges go in the banner.
    const agentIdSet = new Set(nodeIds);
    const renderErrors: string[] = [];
    for (const e of cfg.edges) {
      if (!agentIdSet.has(e.from)) {
        renderErrors.push(
          `Edge "${e.from} → ${e.to}" has unknown source "${e.from}".`,
        );
      }
      if (!agentIdSet.has(e.to)) {
        renderErrors.push(
          `Edge "${e.from} → ${e.to}" has unknown target "${e.to}".`,
        );
      }
    }
    const validEdges = cfg.edges.filter(
      e => agentIdSet.has(e.from) && agentIdSet.has(e.to),
    );
    const endIds = new Set(this.endNodeIds(cfg));

    const startPos = savedPos[START_NODE_ID];
    const endPos   = savedPos[END_NODE_ID];
    const elements: cytoscape.ElementDefinition[] = [
      {
        data: { id: START_NODE_ID, label: 'START' },
        classes: 'virtual-node start-node',
        selectable: false,
        ...(startPos ? { position: { x: startPos.x, y: startPos.y } } : {}),
      },
      ...nodeIds.map(id => {
        const pos = savedPos[id];
        return {
          data: {
            id,
            label: AGENT_LABELS[this.baseAgentId(id)] ?? id,
            color: this.colorForAgentNode(id),
          },
          ...(pos ? { position: { x: pos.x, y: pos.y } } : {}),
        };
      }),
      {
        data: { id: END_NODE_ID, label: 'END' },
        classes: 'virtual-node end-node',
        selectable: false,
        ...(endPos ? { position: { x: endPos.x, y: endPos.y } } : {}),
      },
      // Deterministic edge order so Relayout produces a stable shape.
      // Classification: back-edge wins over conditional when both apply.
      ...(() => {
        const backEdges = this.findBackEdges(cfg);
        const outDegree: Record<string, number> = {};
        for (const e of validEdges) outDegree[e.from] = (outDegree[e.from] ?? 0) + 1;
        return [...validEdges]
          .sort((a, b) => (a.from === b.from ? a.to.localeCompare(b.to) : a.from.localeCompare(b.from)))
          .map(e => {
            const id = `${e.from}-${e.to}`;
            const classes: string[] = [];
            const data: Record<string, unknown> = { id, source: e.from, target: e.to };
            if (backEdges.has(id)) {
              classes.push('edge-loopback');
              // Placeholder cpd; refreshLoopbackCurves re-signs it.
              data['cpd'] = [70];
            } else if (this.isConditionalEdge(e, cfg, outDegree)) {
              classes.push('edge-conditional');
            }
            return { data, ...(classes.length ? { classes: classes.join(' ') } : {}) };
          });
      })(),
      // START → entry virtual edge; delete it to clear `cfg.entry`.
      ...(cfg.entry && cfg.agents[cfg.entry]
        ? [{
            data: {
              id: `${START_NODE_ID}-${cfg.entry}`,
              source: START_NODE_ID,
              target: cfg.entry,
            },
            classes: 'virtual-edge',
          }]
        : []),
      // ?→END virtual edges; delete one to remove its source from `cfg.end`.
      ...nodeIds
        .filter(id => endIds.has(id))
        .map(id => ({
          data: {
            id: `${id}-${END_NODE_ID}`,
            source: id,
            target: END_NODE_ID,
          },
          classes: 'virtual-edge',
        })),
    ];

    if (!this.cy) {
      this.initCytoscape(elements, hasPositions);
    } else {
      this.cy.elements().remove();
      this.cy.add(elements);
      this.cy.resize();
      if (!hasPositions) {
        this.cy.layout({
            name: 'breadthfirst', directed: true, padding: 40, spacingFactor: 1.2,
            nodeDimensionsIncludeLabels: true,
            // Horizontal flow; stretch inter-level, compress intra-level so
            // wide-fan topologies read LTR instead of squeezed into a column.
            transform: (_node: any, pos: any) => ({ x: pos.y * 1.6, y: pos.x * 0.7 }),
          } as any).run();
      }
      this.cy.fit(undefined, 30);
    }
    this.refreshLoopbackCurves();
    if (renderErrors.length > 0) {
      this.validationErrors = renderErrors;
      this.cdr.markForCheck();
    }
  }

  // ─── Node / edge tap handlers ──────────────────────────────────
  onNodeTap(node: NodeSingular): void {
    const id = node.id();
    const isVirtual = id === START_NODE_ID || id === END_NODE_ID;

    if (this.addEdgeMode) {
      if (!this.edgeSource) {
        // Picking the source. END can only ever be a target.
        if (id === END_NODE_ID) return;
        this.edgeSource = id;
        node.addClass('edge-source');
      } else if (this.edgeSource !== id) {
        // Picking the target. START can only ever be a source; START → END
        // would imply an empty graph, which we don't allow either.
        if (id === START_NODE_ID) return;
        this.applyAddEdge(this.edgeSource, id);
        this.cy.getElementById(this.edgeSource).removeClass('edge-source');
        this.edgeSource = null;
        this.addEdgeMode = false;
      }
      this.cdr.markForCheck();
      return;
    }

    if (isVirtual) {
      this.selectedAgent = null;
      this.selectedEdgeId = null;
      this.cdr.markForCheck();
      return;
    }

    this.selectedAgent = id;
    this.selectedEdgeId = null;
    this.syncModelOptions(this.agentBlock?.model ?? '');
    this.cdr.markForCheck();
  }

  onEdgeTap(edge: EdgeSingular): void {
    this.selectedEdgeId = edge.id();
    this.selectedAgent = null;
    this.cdr.markForCheck();
  }

  /** Add-edge-mode handler. START→X sets `cfg.entry`; X→END toggles
   * X's membership in `cfg.end`; otherwise adds a normal edge. */
  private applyAddEdge(source: string, target: string): void {
    if (!this.cy || !this.currentConfig) return;
    if (!this.isLoadedConfig) return;

    if (source === START_NODE_ID) {
      this.currentConfig.entry = target;
      this.refreshBoundaryEdges();
      this.markDirty();
      return;
    }

    if (target === END_NODE_ID) {
      // Toggle `source` in `cfg.end`. Outgoing edges are independent —
      // an end-listed node can still route to other targets.
      const ends = this.endNodeIds(this.currentConfig);
      const idx = ends.indexOf(source);
      if (idx >= 0) {
        ends.splice(idx, 1);
      } else {
        ends.push(source);
      }
      // Stabilize serialization to list[str] once touched.
      this.currentConfig.end = ends;
      this.refreshBoundaryEdges();
      this.markDirty();
      return;
    }

    const edgeId = `${source}-${target}`;
    if (this.cy.getElementById(edgeId).length > 0) return;
    this.cy.add({ data: { id: edgeId, source, target } });
    this.persistEdgesFromGraph();
    this.refreshBoundaryEdges();
    // Re-classify all edges — adding one edge can flip back-edge status
    // of others. `findBackEdges` is a full-graph DFS but cheap (<20 nodes).
    this.applyEdgeClasses();
    this.refreshLoopbackCurves();
    this.markDirty();
  }

  /** Re-evaluate every edge's `.edge-loopback` / `.edge-conditional`
   * class against the current `cfg.edges` topology. Used by `addEdge`
   * after a structural mutation; `renderConfig` builds its initial
   * classification inline at `cy.add()` time so this is a no-op on
   * first render. */
  private applyEdgeClasses(): void {
    if (!this.cy || !this.currentConfig) return;
    const cfg = this.currentConfig;
    const backEdges = this.findBackEdges(cfg);
    const outDegree: Record<string, number> = {};
    for (const e of cfg.edges) outDegree[e.from] = (outDegree[e.from] ?? 0) + 1;

    for (const e of cfg.edges) {
      const id = `${e.from}-${e.to}`;
      const cyEdge = this.cy.getElementById(id);
      if (cyEdge.length === 0) continue;
      cyEdge.removeClass('edge-loopback edge-conditional');
      if (backEdges.has(id)) {
        cyEdge.addClass('edge-loopback');
        // Seed a positive cpd so the arc renders something sensible
        // until `refreshLoopbackCurves` re-evaluates the sign with
        // real node positions.
        if (!cyEdge.data('cpd')) cyEdge.data('cpd', [70]);
      } else if (this.isConditionalEdge(e, cfg, outDegree)) {
        cyEdge.addClass('edge-conditional');
      }
    }
  }

  /** Recompute virtual START → entry and ?→END edges to mirror the canonical
   * state (`cfg.entry` + leaf detection). Called after any structural edit
   * — add-edge, delete, palette-drop. Cheap: just removes/re-adds the
   * marked-as-virtual edges. */
  private refreshBoundaryEdges(): void {
    if (!this.cy || !this.currentConfig) return;
    this.cy.edges().forEach(e => { if (e.hasClass('virtual-edge')) e.remove(); });

    const entry = this.currentConfig.entry;
    if (entry && this.cy.getElementById(entry).length > 0) {
      this.cy.add({
        data: { id: `${START_NODE_ID}-${entry}`, source: START_NODE_ID, target: entry },
        classes: 'virtual-edge',
      });
    }

    const endIds = new Set(this.endNodeIds(this.currentConfig));
    endIds.forEach(id => {
      if (this.cy.getElementById(id).length > 0) {
        this.cy.add({
          data: { id: `${id}-${END_NODE_ID}`, source: id, target: END_NODE_ID },
          classes: 'virtual-edge',
        });
      }
    });
  }

  // ─── In-memory mutations of currentConfig ─────────────────────
  private persistEdgesFromGraph(): void {
    if (!this.currentConfig || !this.cy) return;
    // Skip virtual edges; entry / end live separately in the canonical config.
    this.currentConfig.edges = this.cy.edges()
      .filter(e => !e.hasClass('virtual-edge'))
      .map(e => ({
        from: e.data('source') as string,
        to: e.data('target') as string,
      }));
  }

  private persistNodesFromGraph(): void {
    if (!this.currentConfig || !this.cy) return;
    const presentIds = new Set(
      this.cy.nodes()
        .map(n => n.id())
        .filter(id => id !== START_NODE_ID && id !== END_NODE_ID),
    );
    for (const name of Object.keys(this.currentConfig.agents)) {
      if (!presentIds.has(name)) {
        delete this.currentConfig.agents[name];
      }
    }
    // Drop dangling entry/end pointers after node deletion.
    if (this.currentConfig.entry && !this.currentConfig.agents[this.currentConfig.entry]) {
      this.currentConfig.entry = '';
    }
    const ends = this.endNodeIds(this.currentConfig).filter(
      id => !!this.currentConfig!.agents[id],
    );
    this.currentConfig.end = ends;
    this.persistEdgesFromGraph();
  }

  // ─── Graph editing tools ───────────────────────────────────────
  toggleAddEdgeMode(): void {
    this.addEdgeMode = !this.addEdgeMode;
    if (!this.addEdgeMode && this.edgeSource) {
      this.cy.getElementById(this.edgeSource).removeClass('edge-source');
      this.edgeSource = null;
    }
  }

  /** Delete/Backspace shortcut for the toolbar Delete button. */
  @HostListener('document:keydown', ['$event'])
  onKeyDown(ev: KeyboardEvent): void {
    if (ev.key !== 'Delete' && ev.key !== 'Backspace') return;
    const target = ev.target as HTMLElement | null;
    const tag = target?.tagName?.toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return;
    if (!this.isLoadedConfig) return;
    if (!this.cy || this.cy.$(':selected').length === 0) return;
    ev.preventDefault();
    this.deleteSelected();
  }

  deleteSelected(): void {
    if (!this.currentConfig) return;
    const selected = this.cy.$(':selected');
    if (!selected.length) return;

    // Process virtual edges first; deleting them is a config metadata edit.
    selected.edges().filter(e => e.hasClass('virtual-edge')).forEach(e => {
      const source = e.data('source') as string;
      const target = e.data('target') as string;
      if (source === START_NODE_ID && this.currentConfig) {
        this.currentConfig.entry = '';
      } else if (target === END_NODE_ID && this.currentConfig) {
        const ends = this.endNodeIds(this.currentConfig).filter(n => n !== source);
        this.currentConfig.end = ends;
      }
    });

    // Real graph elements; virtual nodes are selectable:false but filter anyway.
    const real = selected.filter(el =>
      el.id() !== START_NODE_ID &&
      el.id() !== END_NODE_ID &&
      !el.hasClass('virtual-edge'),
    );
    if (real.length > 0) {
      real.remove();
      this.persistNodesFromGraph();
    }

    this.refreshBoundaryEdges();
    this.selectedAgent = null;
    this.selectedEdgeId = null;
    this.markDirty();
  }

  /** Rename a node — rewrites every `cfg.agents` key, `entry`, `end`,
   * edge endpoint, cytoscape id, and saved-position slot. */
  renameSelected(): void {
    if (!this.isLoadedConfig || !this.currentConfig || !this.cy) return;
    const oldName = this.selectedAgent;
    if (!oldName) return;
    if (oldName === START_NODE_ID || oldName === END_NODE_ID) return;

    const proposed = window.prompt(`Rename node "${oldName}" to:`, oldName);
    if (proposed === null) return;
    const newName = proposed.trim();
    if (!newName || newName === oldName) return;

    if (newName === START_NODE_ID || newName === END_NODE_ID) {
      window.alert(`"${newName}" is a reserved sentinel id. Pick a different name.`);
      return;
    }
    if (Object.prototype.hasOwnProperty.call(this.currentConfig.agents, newName)) {
      window.alert(
        `A node named "${newName}" already exists in this config. Pick a different name.`,
      );
      return;
    }

    // 1) Rebuild agents preserving insertion order.
    this.currentConfig.agents = Object.fromEntries(
      Object.entries(this.currentConfig.agents).map(
        ([k, v]) => [k === oldName ? newName : k, v],
      ),
    );
    // 2) Rewire scalar / list references.
    if (this.currentConfig.entry === oldName) {
      this.currentConfig.entry = newName;
    }
    this.currentConfig.end = this.endNodeIds(this.currentConfig).map(
      n => n === oldName ? newName : n,
    );
    for (const e of this.currentConfig.edges) {
      if (e.from === oldName) e.from = newName;
      if (e.to   === oldName) e.to   = newName;
    }
    // 3) Snapshot positions first so untouched nodes don't get re-laid-out.
    this.saveNodePositions();
    const posKey = this.currentConfigName;
    if (posKey && this.svc.nodePositions[posKey]?.[oldName]) {
      this.svc.nodePositions[posKey][newName] = this.svc.nodePositions[posKey][oldName];
      delete this.svc.nodePositions[posKey][oldName];
    }
    // 4) Rebuild the whole canvas — cytoscape can't rename a node id in place.
    this.renderConfig(this.currentConfig);
    this.relayout();
    this.selectedAgent = newName;
    this.cy.getElementById(newName).select();
    this.markDirty();
    this.cdr.markForCheck();
  }


  relayout(): void {
    if (!this.cy) return;
    if (this.currentConfigName) delete this.svc.nodePositions[this.currentConfigName];
    this.cy.layout({
            name: 'breadthfirst', directed: true, padding: 40, spacingFactor: 1.2,
            nodeDimensionsIncludeLabels: true,
            // LTR flow; stretch inter-level, compress intra-level for wide fans.
            transform: (_node: any, pos: any) => ({ x: pos.y * 1.6, y: pos.x * 0.7 }),
          } as any).run();
    this.cy.fit(undefined, 40);
    this.saveNodePositions();
  }

  /** Tear down cytoscape and re-fetch from disk — manual canvas recovery. */
  reloadGraph(): void {
    const name = this.currentConfigName;
    if (!name) return;
    if (this.isLoadedConfig && this.dirty) {
      if (!window.confirm(
        `Reload "${name}"? You have unsaved edits — these will be discarded ` +
        `and the on-disk version of the config will replace the current canvas.`
      )) return;
    }
    delete this.svc.nodePositions[name];
    this.selectedAgent = null;
    this.selectedEdgeId = null;
    this.cy?.destroy();
    this.cy = undefined as unknown as Core;
    this.loadPredefined(name);
  }

  /** History panel; only opens for loaded (versioned) configs. */
  openHistoryPanel(): void {
    if (!this.isLoadedConfig) return;
    this.historyPanelOpen = true;
  }

  /** Restore a historical version + persist as a new commit. */
  onHistoryRestore(restored: UnifiedConfig): void {
    if (!this.currentConfigName) return;
    this.svc.currentConfig = restored;
    delete this.svc.nodePositions[this.currentConfigName];
    this.cy?.destroy();
    this.cy = undefined as unknown as Core;
    this.renderConfig(restored);
    this.historyPanelOpen = false;
    this.svc.validated = true;
    this._persistCurrentConfig();
    this.cdr.markForCheck();
  }

  fitGraph(): void { this.cy?.fit(undefined, 40); }

  // ─── World-space view state ─────────────────────────────────────
  bgPanX = 0;
  bgPanY = 0;
  cyZoomLevel = 1;
  cyContainerW = 800;
  cyContainerH = 600;

  get gridTransform(): string {
    return `translate(${this.bgPanX} ${this.bgPanY}) scale(${this.cyZoomLevel})`;
  }

  /** Visible world rect — used by grid-cover rects to span the viewport. */
  get visWorld(): { x: number; y: number; w: number; h: number } {
    const z = this.cyZoomLevel || 1;
    return {
      x: -this.bgPanX / z,
      y: -this.bgPanY / z,
      w: this.cyContainerW / z,
      h: this.cyContainerH / z,
    };
  }

  /** Toggle for the world-space grid layer. Signal so the @if in the
   * template tracks it reactively; flip via the (currently unwired)
   * future grid-on/off control. Default ON so the layout reference
   * is visible without configuration. */
  showGrid = signal(true);

  /** Collapse state for the left "Configurations" panel. When true the
   * box shrinks to a narrow rail showing only the toggle chevron. */
  leftCollapsed = signal(false);
  toggleLeftCollapsed(): void { this.leftCollapsed.set(!this.leftCollapsed()); }

  // ─── On-canvas zoom controls ───────────────────────────────────
  /** Current zoom level surfaced as a percentage to the in-canvas
   * readout. Kept in sync with `cy.zoom()` via `syncCyView`. */
  zoomPercent = 100;

  /** Single source of truth for the world-space view state. Reads
   * cy's pan/zoom/dimensions and updates every dependent field +
   * triggers CD. Hooked to `cy.on('pan'|'zoom'|'resize')` so the
   * parallax bg, SVG grid, and zoom readout all stay live. */
  private syncCyView(): void {
    if (!this.cy) return;
    const p = this.cy.pan();
    const z = this.cy.zoom();
    this.bgPanX = p.x;
    this.bgPanY = p.y;
    this.cyZoomLevel = z;
    this.cyContainerW = this.cy.width();
    this.cyContainerH = this.cy.height();
    this.zoomPercent = Math.round(z * 100);
    this.cdr.markForCheck();
  }

  /** 1.2x per click — matches cytoscape's wheel step. */
  zoomIn(): void { this.stepZoom(1.2); }
  zoomOut(): void { this.stepZoom(1 / 1.2); }

  private stepZoom(factor: number): void {
    if (!this.cy) return;
    const next = this.cy.zoom() * factor;
    const min = this.cy.minZoom();
    const max = this.cy.maxZoom();
    const clamped = Math.min(max, Math.max(min, next));
    // Anchor on canvas centre (cy.zoom(level) alone anchors at 0,0).
    const w = this.cy.width();
    const h = this.cy.height();
    this.cy.zoom({ level: clamped, renderedPosition: { x: w / 2, y: h / 2 } });
  }

  // ─── Drag from palette ─────────────────────────────────────────
  onGraphDragOver(event: DragEvent): void {
    event.preventDefault();
    event.dataTransfer!.dropEffect = 'copy';
  }

  onGraphDrop(event: DragEvent): void {
    event.preventDefault();
    if (!this.isLoadedConfig) return;
    const type = event.dataTransfer?.getData('agent-type');
    if (!type || !this.cy || !this.currentConfig) return;
    // Optional variant key from the new palette; legacy drags fall back to built-in.
    const variantKey = event.dataTransfer?.getData('agent-variant') || '';
    const variant = variantKey ? this.findVariant(variantKey) : null;

    const rect = this.graphEl.nativeElement.getBoundingClientRect();
    const pan = this.cy.pan();
    const zoom = this.cy.zoom();
    const modelX = (event.clientX - rect.left - pan.x) / zoom;
    const modelY = (event.clientY - rect.top - pan.y) / zoom;

    const taken = new Set(Object.keys(this.currentConfig.agents));
    // Repo-prefixed id; collisions get `_<n>` via suggestNodeId.
    let base: string;
    if (variant && variant.repo !== 'evomas') {
      base = `${normalizeNodeBase(variant.repo)}_${normalizeNodeBase(variant.name || type)}`;
    } else {
      base = `evomas_${normalizeNodeBase(type)}`;
    }
    if (!base) base = normalizeNodeBase(type) || 'agent';
    const id = taken.has(base) ? suggestNodeId(base, taken) : base;

    this.cy.add({
      data: { id, label: id, color: this.typeColor[type] ?? '#888' },
      position: { x: modelX, y: modelY },
    });
    this.currentConfig.agents[id] = this.defaultAgentBlock(type, variant);
    // Fresh node has no outgoing edges; show its boundary status immediately.
    this.refreshBoundaryEdges();
    this.markDirty();
  }

  getAgentColorStyle(agent: string): string {
    return this.colorForAgentNode(agent);
  }

  /** Type-catalog color; falls back to the legacy node-id palette. */
  private colorForAgentNode(nodeId: string): string {
    const cls = this.currentConfig?.agents?.[nodeId]?.class ?? '';
    const type = this.classToType[cls];
    if (type && this.typeColor[type]) return this.typeColor[type];
    return AGENT_COLORS[this.baseAgentId(nodeId)] ?? '#888';
  }

  private defaultAgentBlock(type: string, variant?: AgentVariant | null): AgentBlock {
    const meta = this.agentTypes.find(t => t.type === type);
    const cfg = (meta?.default_config ?? {}) as Record<string, unknown>;
    // Repo variants override prompts + tools; config knobs stay from the type.
    const useVariant = variant && variant.repo !== 'evomas';
    const variantTools = useVariant ? (variant?.default_tools ?? []) : (meta?.default_tools ?? []);
    const block: AgentBlock = {
      class: type,
      variant: variant?.key ?? `evomas:${type}`,
      // Defaults mirror the AgentConfig pydantic schema.
      model:          (cfg['model']          as string)  ?? 'qwen3.5:9b',
      think:          (cfg['think']          as boolean) ?? true,
      num_ctx:        (cfg['num_ctx']        as number)  ?? 4096,
      stream:         (cfg['stream']         as boolean) ?? true,
      temperature:    (cfg['temperature']    as number)  ?? 0.2,
      top_k:          (cfg['top_k']          as number)  ?? 40,
      top_p:          (cfg['top_p']          as number)  ?? 0.9,
      min_p:          (cfg['min_p']          as number)  ?? 0.0,
      repeat_penalty: (cfg['repeat_penalty'] as number)  ?? 1.1,
      repeat_last_n:  (cfg['repeat_last_n']  as number)  ?? 64,
      seed:           (cfg['seed']           as number)  ?? 0,
      num_predict:    (cfg['num_predict']    as number)  ?? -1,
      stop:           (cfg['stop']           as string[]) ?? [],
      state: [],
      tools: variantTools.map(name => ({ name, params: {} })),
      prompts: {
        system: useVariant ? (variant?.default_system ?? '') : (meta?.default_system ?? ''),
        user:   useVariant ? (variant?.default_user   ?? '') : (meta?.default_user   ?? ''),
        proxy:  useVariant ? (variant?.default_proxy  ?? '') : '',
      },
    };
    return block;
  }

  // ─── Reset-to-defaults (per section) ────────────────────────────
  resetParams(): void {
    if (!this.isLoadedConfig) return;
    const block = this.agentBlock;
    if (!block) return;
    const id = this.selectedAgent;
    if (!id) return;
    const meta = this.agentTypes.find(t => t.type === (this.classToType[block.class] ?? block.class));
    if (!meta) return;
    if (!window.confirm(
      `Reset parameters of agent "${id}" to the ${meta.type} defaults? `
      + `Model + every knob will be overwritten. Other fields (tools, prompts) stay.`
    )) return;

    const cfg = (meta.default_config ?? {}) as Record<string, unknown>;
    block.model          = (cfg['model']          as string)   ?? 'qwen3.5:9b';
    block.think          = (cfg['think']          as boolean)  ?? true;
    block.num_ctx        = (cfg['num_ctx']        as number)   ?? 4096;
    block.stream         = (cfg['stream']         as boolean)  ?? true;
    block.temperature    = (cfg['temperature']    as number)   ?? 0.2;
    block.top_k          = (cfg['top_k']          as number)   ?? 40;
    block.top_p          = (cfg['top_p']          as number)   ?? 0.9;
    block.min_p          = (cfg['min_p']          as number)   ?? 0.0;
    block.repeat_penalty = (cfg['repeat_penalty'] as number)   ?? 1.1;
    block.repeat_last_n  = (cfg['repeat_last_n']  as number)   ?? 64;
    block.seed           = (cfg['seed']           as number)   ?? 0;
    block.num_predict    = (cfg['num_predict']    as number)   ?? -1;
    block.stop           = (cfg['stop']           as string[]) ?? [];
    this.syncModelOptions(block.model);
    this.markDirty();
    this.cdr.markForCheck();
  }

  resetTools(): void {
    if (!this.isLoadedConfig) return;
    const block = this.agentBlock;
    if (!block) return;
    const id = this.selectedAgent;
    if (!id) return;
    const meta = this.agentTypes.find(t => t.type === (this.classToType[block.class] ?? block.class));
    if (!meta) return;
    if (!window.confirm(
      `Reset tools of agent "${id}" to the ${meta.type} defaults? `
      + `Custom tool params will be lost.`
    )) return;

    const variant = meta.variants?.find(v => v.key === block.variant);
    const useVariant = !!variant && variant.repo !== 'evomas';
    const defaults = useVariant ? (variant?.default_tools ?? []) : (meta.default_tools ?? []);
    block.tools = defaults.map(name => ({ name, params: {} }));
    this.toolParamsDraft = {};
    this.toolParamsError = {};
    this.markDirty();
    this.cdr.markForCheck();
  }

  resetPrompts(): void {
    if (!this.isLoadedConfig) return;
    const block = this.agentBlock;
    if (!block) return;
    const id = this.selectedAgent;
    if (!id) return;
    const meta = this.agentTypes.find(t => t.type === (this.classToType[block.class] ?? block.class));
    if (!meta) return;
    if (!window.confirm(
      `Reset prompts of agent "${id}" to the ${meta.type} defaults? `
      + `Custom system/user/proxy text will be lost.`
    )) return;

    block.prompts = {};
    this.markDirty();
    this.cdr.markForCheck();
  }

  // ─── Agent block edit ──────────────────────────────────────────
  onAgentField<K extends keyof AgentBlock>(key: K, value: AgentBlock[K]): void {
    if (!this.isLoadedConfig) return;
    const block = this.agentBlock;
    if (!block) return;
    block[key] = value;
    if (key === 'model') this.syncModelOptions(value as string);
    this.markDirty();
  }

  // ─── Save (disk) ───────────────────────────────────────────────
  saveFlash = false;
  saveError = '';

  /** Loaded configs are writable; predefined are read-only. */
  get isLoadedConfig(): boolean {
    if (!this.currentConfigName) return false;
    return this.predefinedConfigs.some(
      c => c.stem === this.currentConfigName && c.source === 'loaded',
    );
  }

  saveToDisk(): void {
    if (!this.currentConfig || !this.currentConfigName) return;
    if (!this.isLoadedConfig) return;
    // Pre-flight validation is non-blocking; runtime is the real gate.
    const { errors, warnings } = this.validateConfig();
    this.validationErrors = errors;
    this.validationWarnings = warnings;
    if (!window.confirm(
      `Overwrite evomas/config/loaded/${this.currentConfigName}.json with the current edits? The previous file will be gone.`
    )) return;
    this._persistCurrentConfig();
  }

  /** Persist without re-confirming; callers own their own confirm dialog. */
  private _persistCurrentConfig(): void {
    if (!this.currentConfig || !this.currentConfigName) return;
    this.api.saveLoadedConfig(this.currentConfigName, this.currentConfig, true).subscribe({
      next: () => {
        this.saveError = '';
        this.saveFlash = true;
        this.svc.dirty = false;
        setTimeout(() => { this.saveFlash = false; this.cdr.markForCheck(); }, 1200);
        this.cdr.markForCheck();
      },
      error: err => {
        this.saveError = err?.error?.detail ?? err?.message ?? 'Save failed';
        this.cdr.markForCheck();
      },
    });
  }

  // ─── Tools editor ──────────────────────────────────────────────
  toolParamsDraft: Record<number, string> = {};
  toolParamsError: Record<number, string> = {};

  /** True when the active node was seeded from a non-EvoMas variant. In
   * that case the type's built-in defaults must NOT leak in as a fallback:
   * an empty `prompts.system` or `tools` array means the variant explicitly
   * has no value for that slot, not "fall back to the EvoMas built-in". */
  private get blockHasRepoVariant(): boolean {
    const v = this.agentBlock?.variant;
    return !!v && !v.startsWith('evomas:');
  }

  get currentTools(): AgentTool[] {
    if (!this.agentBlock) return [];
    // When the JSON block doesn't carry an explicit `tools` array, surface
    // the type's DEFAULT_TOOLS as a read-only preview. The first add/remove
    // call materializes them into the block so subsequent edits behave the
    // way they always have.
    if (this.agentBlock.tools && this.agentBlock.tools.length > 0) {
      return this.agentBlock.tools;
    }
    // Non-EvoMas variants own their tool list (possibly empty); no fallback.
    if (this.blockHasRepoVariant) {
      if (!this.agentBlock.tools) this.agentBlock.tools = [];
      return this.agentBlock.tools;
    }
    const t = this.currentAgentType;
    if (t && t.default_tools.length > 0) {
      return t.default_tools.map(name => ({ name, params: {} }));
    }
    if (!this.agentBlock.tools) this.agentBlock.tools = [];
    return this.agentBlock.tools;
  }

  /** Copy type defaults into the block so add/remove operates on a real array. */
  private materializeDefaultTools(): void {
    if (!this.agentBlock) return;
    if (this.agentBlock.tools && this.agentBlock.tools.length > 0) return;
    if (this.blockHasRepoVariant) {
      if (!this.agentBlock.tools) this.agentBlock.tools = [];
      return;
    }
    const t = this.currentAgentType;
    this.agentBlock.tools = (t?.default_tools ?? []).map(name => ({ name, params: {} }));
  }

  /** Tool names in the registry that the current agent has not yet added. */
  get unusedToolNames(): string[] {
    const used = new Set(this.currentTools.map(t => t.name));
    return this.availableTools.map(t => t.name).filter(n => !used.has(n));
  }

  /** Leading "(empty)" option — adding it is a no-op. */
  emptyToolOption: SelectOption[] = [{ value: '', label: '(empty)' }];

  /** Bucket unused tools into one `<optgroup>` per `repo`. */
  get unusedToolOptionGroups(): SelectOptionGroup[] {
    const repoByName = new Map<string, string>();
    for (const t of this.availableTools) {
      repoByName.set(t.name, t.repo || FALLBACK_REPO);
    }
    const buckets = new Map<string, string[]>();
    for (const name of this.unusedToolNames) {
      const repo = repoByName.get(name) || FALLBACK_REPO;
      const arr = buckets.get(repo);
      if (arr) arr.push(name); else buckets.set(repo, [name]);
    }
    for (const arr of buckets.values()) arr.sort();
    const seen = new Set<string>();
    const out: SelectOptionGroup[] = [];
    for (const repo of REPO_GROUP_ORDER) {
      if (buckets.has(repo)) {
        out.push({ label: repo, items: buckets.get(repo)! });
        seen.add(repo);
      }
    }
    const remaining = [...buckets.keys()].filter(r => !seen.has(r)).sort();
    for (const repo of remaining) {
      out.push({ label: repo, items: buckets.get(repo)! });
    }
    return out;
  }

  toolDescription(name: string): string {
    return this.availableTools.find(t => t.name === name)?.description ?? '';
  }

  addTool(name: string): void {
    if (!this.isLoadedConfig) return;
    if (!name || !this.agentBlock) return;
    // Copy any fallback defaults into the block first so add lands on top.
    this.materializeDefaultTools();
    if (this.agentBlock.tools!.some(t => t.name === name)) return;
    this.agentBlock.tools!.push({ name, params: {} });
    this.markDirty();
    this.cdr.markForCheck();
  }

  removeTool(idx: number): void {
    if (!this.isLoadedConfig) return;
    // Materialize first so removing a "ghost" default actually persists.
    this.materializeDefaultTools();
    if (!this.agentBlock?.tools) return;
    this.agentBlock.tools.splice(idx, 1);
    delete this.toolParamsDraft[idx];
    delete this.toolParamsError[idx];
    this.markDirty();
    this.cdr.markForCheck();
  }

  /** Pretty-printed JSON the textarea is bound to. */
  paramsJson(idx: number): string {
    if (this.toolParamsDraft[idx] !== undefined) return this.toolParamsDraft[idx];
    const params = this.currentTools[idx]?.params ?? {};
    return Object.keys(params).length === 0 ? '{}' : JSON.stringify(params, null, 2);
  }

  onParamsInput(idx: number, value: string): void {
    if (!this.isLoadedConfig) return;
    this.toolParamsDraft[idx] = value;
    try {
      const parsed = value.trim() ? JSON.parse(value) : {};
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('must be a JSON object');
      }
      this.currentTools[idx].params = parsed as Record<string, unknown>;
      delete this.toolParamsError[idx];
      this.markDirty();
    } catch (err) {
      this.toolParamsError[idx] = (err as Error).message;
    }
  }

  // ─── Inspector section toggles ─────────────────────────────────
  paramsOpen = true;
  toolsOpen = true;
  promptsOpen = true;

  // ─── Prompt editor ─────────────────────────────────────────────
  /** '' = collapsed, otherwise the visible slot key. */
  promptTab: 'system' | 'user' | 'proxy' | '' = '';

  togglePromptTab(slot: 'system' | 'user' | 'proxy'): void {
    this.promptTab = this.promptTab === slot ? '' : slot;
  }

  /** AgentType for the active block; drives DEFAULT_* fallbacks. */
  get currentAgentType(): AgentType | null {
    const cls = this.agentBlock?.class;
    if (!cls) return null;
    const typeName = this.classToType[cls] ?? cls;
    return this.agentTypes.find(t => t.type === typeName) ?? null;
  }

  getPrompt(slot: 'system' | 'user' | 'proxy'): string {
    const explicit = this.agentBlock?.prompts?.[slot];
    if (typeof explicit === 'string' && explicit.length > 0) return explicit;
    // Repo variants own their (possibly empty) prompts; no type fallback.
    if (this.blockHasRepoVariant) return '';
    const t = this.currentAgentType;
    if (slot === 'system') return t?.default_system ?? '';
    if (slot === 'user')   return t?.default_user ?? '';
    return '';
  }

  onPromptChange(slot: 'system' | 'user' | 'proxy', value: string): void {
    if (!this.isLoadedConfig) return;
    const block = this.agentBlock;
    if (!block) return;
    if (!block.prompts) block.prompts = {};
    block.prompts[slot] = value;
    this.markDirty();
  }

  // ─── Validation ────────────────────────────────────────────────
  validationErrors: string[] = [];
  /** Soft-fail diagnostics — graph still compiles. */
  validationWarnings: string[] = [];
  validateFlash = false;

  /** Pure — safe to call from both Validate clicks and pre-save blocks. */
  validateConfig(): { valid: boolean; errors: string[]; warnings: string[] } {
    const cfg = this.currentConfig;
    const errors: string[] = [];
    const warnings: string[] = [];
    if (!cfg) return { valid: false, errors: ['No configuration loaded.'], warnings };

    const agentIds = Object.keys(cfg.agents);
    if (agentIds.length === 0) {
      errors.push('Configuration has no agents.');
      return { valid: false, errors, warnings };
    }

    // 1. entry must be set and refer to an existing agent.
    if (!cfg.entry || !cfg.entry.trim()) {
      errors.push('`entry` is empty — no node will be the START successor.');
    } else if (!cfg.agents[cfg.entry]) {
      errors.push(`\`entry\` points at "${cfg.entry}" but no agent with that id exists.`);
    }

    // 2. end must be non-empty and every entry must refer to an existing agent.
    const ends = this.endNodeIds(cfg);
    if (ends.length === 0) {
      errors.push('`end` is empty — no node is allowed to route to END.');
    }
    for (const id of ends) {
      if (!cfg.agents[id]) {
        errors.push(`\`end\` lists "${id}" but no agent with that id exists.`);
      }
    }

    // 3. every edge endpoint must refer to an existing agent.
    for (const e of cfg.edges) {
      if (!cfg.agents[e.from]) {
        errors.push(`Edge "${e.from} → ${e.to}" has unknown source "${e.from}".`);
      }
      if (!cfg.agents[e.to]) {
        errors.push(`Edge "${e.from} → ${e.to}" has unknown target "${e.to}".`);
      }
    }

    // 4+5. Shape diagnostics (warnings, not errors): orphan dead-ends
    //      and fully-disconnected nodes. Dedupe to the more specific case.
    const hasOutgoing = new Set<string>(cfg.edges.map(e => e.from));
    const hasIncoming = new Set<string>(cfg.edges.map(e => e.to));
    const endSet = new Set(ends);
    for (const id of agentIds) {
      const incoming = hasIncoming.has(id);
      const outgoing = hasOutgoing.has(id);
      const isEntry  = cfg.entry === id;
      const inEnd    = endSet.has(id);
      if (!incoming && !outgoing && !isEntry) {
        warnings.push(
          `Node "${id}" is disconnected — no incoming or outgoing edges and not the entry. ` +
          `It will never execute at runtime.`,
        );
      } else if (!outgoing && !inEnd) {
        warnings.push(
          `Node "${id}" has no outgoing edges and is not in \`end\` — it's an orphan ` +
          `dead-end. The branch that reaches it will stall until the runtime ` +
          `recursion-limit aborts the run.`,
        );
      }
    }

    // 6. BFS from `entry` must reach at least one degree-0 end-set node.
    //    Only degree-0 `end` nodes get the static `→ END` wire at runtime.
    if (cfg.entry && cfg.agents[cfg.entry] && ends.length > 0) {
      const outBySource: Record<string, string[]> = {};
      for (const e of cfg.edges) (outBySource[e.from] ||= []).push(e.to);
      const reachable = new Set<string>();
      const frontier: string[] = [cfg.entry];
      while (frontier.length) {
        const node = frontier.shift()!;
        if (reachable.has(node)) continue;
        reachable.add(node);
        for (const t of (outBySource[node] || [])) frontier.push(t);
      }
      const endZeroDegree = ends.filter(id => !outBySource[id]);
      if (endZeroDegree.length === 0) {
        errors.push(
          `\`end\` has no degree-0 nodes — every end-set node has outgoing edges. ` +
          `At runtime only degree-0 end-set nodes get the static \`→ END\` wire, ` +
          `so START can never reach END.`,
        );
      } else if (!endZeroDegree.some(id => reachable.has(id))) {
        errors.push(
          `START cannot reach END: BFS from entry "${cfg.entry}" never reaches a ` +
          `degree-0 end-set node (candidates: ${endZeroDegree.map(s => `"${s}"`).join(', ')}). ` +
          `Add an edge path from "${cfg.entry}" to one of them.`,
        );
      }
      // Warning (not error): nodes defined in `cfg.agents` but never
      // reached by the BFS from entry. Mirrors the runtime warning at
      // `graph_builder._build_graph()` — the graph still compiles, but
      // those nodes will never execute (orphan inference cost). Skip
      // the entry itself; it's always reachable by definition.
      const unreachable = agentIds.filter(
        id => id !== cfg.entry && !reachable.has(id),
      );
      if (unreachable.length > 0) {
        warnings.push(
          `${unreachable.length} node(s) unreachable from entry "${cfg.entry}": ` +
          `${unreachable.map(s => `"${s}"`).join(', ')}. These will never execute ` +
          `at runtime — connect them with edges or remove them from \`agents\`.`,
        );
      }
    }

    return { valid: errors.length === 0, errors, warnings };
  }

  /** Toolbar Validate button: surface the result inline. On success,
   * flash a transient green tick reusing the same pattern as Save. */
  validate(): void {
    const { valid, errors, warnings } = this.validateConfig();
    this.validationErrors = errors;
    this.validationWarnings = warnings;
    // User has now acknowledged any diagnostics — clear unvalidated flag.
    this.svc.validated = true;
    // Green flash only when there's nothing at all to surface.
    if (valid && warnings.length === 0) {
      this.validateFlash = true;
      setTimeout(() => { this.validateFlash = false; this.cdr.markForCheck(); }, 1500);
    }
    this.cdr.markForCheck();
  }

  dismissValidationErrors(): void {
    this.validationErrors = [];
  }

  dismissValidationWarnings(): void {
    this.validationWarnings = [];
  }
}
