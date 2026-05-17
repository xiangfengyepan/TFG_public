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
import {
  EvoButtonComponent, EvoSliderComponent, EvoSpinboxComponent, EvoBoxComponent,
  EvoSelectComponent, EvoSwitchComponent, EvoHelpPopoverComponent,
  EvoAgentTypePickerComponent,
} from '../../components/index';
import { SelectOption, SelectOptionGroup } from '../../components/select/evo-select.component';

/** Owner label rendered in the "Add tool" dropdown for tools that the
 * `/api/tools` endpoint doesn't tag with a `repo` field (legacy
 * responses, or missing field for some reason). Anything without a
 * `repo` is treated as an EvoMas-core helper. */
const FALLBACK_REPO = 'evomas';

/** Fixed display order for the "Add tool" dropdown's `<optgroup>`s.
 * `evomas` first so the workspace-I/O / patch helpers are at the top
 * of the list; the rest alphabetical for predictability. Any repo
 * surfaced by `/api/tools` that isn't in this list is appended at the
 * end (alpha-sorted) so a newly-added bundle still shows up without a
 * code change here. */
const REPO_GROUP_ORDER: readonly string[] = ['evomas'];

/** Sentinel ids for the virtual flow-boundary nodes the topology page renders.
 * They are NOT part of `cfg.agents` and NOT serialized into `cfg.edges`; the
 * canonical config keeps using `cfg.entry` for the entry node and `cfg.end`
 * for the node(s) that route to langgraph END (see
 * `evomas/core/workflow/graph_builder.py`).
 * These pickled ids are guarded against collision by their `__` prefix +
 * suffix; an agent named verbatim `__START__` / `__END__` would clash, but
 * the JSON schema doesn't allow that today (TYPE_REGISTRY classes don't use
 * those names). */
const START_NODE_ID = '__START__';
const END_NODE_ID   = '__END__';

@Component({
  selector: 'app-topology',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    EvoButtonComponent, EvoSliderComponent, EvoSpinboxComponent, EvoBoxComponent,
    EvoSelectComponent, EvoSwitchComponent, EvoHelpPopoverComponent,
    EvoAgentTypePickerComponent,
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

  get modelSelectOptions(): string[] { return this.svc.modelSelectOptions; }
  set modelSelectOptions(v: string[]) { this.svc.modelSelectOptions = v; }

  get addEdgeMode(): boolean { return this.svc.addEdgeMode; }
  set addEdgeMode(v: boolean) { this.svc.addEdgeMode = v; }

  /** True when the active config has uncommitted in-memory edits. Drives the
   * toolbar's "unsaved" chip; reset on `setCurrentConfig` (config swap) and
   * on a successful `saveToDisk`. */
  get dirty(): boolean { return this.svc.dirty; }
  /** True when the active config has been validated since the last edit.
   * Drives the toolbar's "unvalidated" chip + gates the Save button.
   * Cleared (= true) by the Validate toolbar action regardless of error
   * count; flipped to false by every `markDirty()` call. */
  get validated(): boolean { return this.svc.validated; }
  /** Tag the active config as having unsaved + unvalidated changes. Call
   * from every site that mutates `currentConfig` (palette drop, edge
   * add/delete, node delete, right-pane field edits, prompt edits,
   * tool edits, ...). Pairs the dirty and unvalidated flags so the user
   * sees both chips light up the moment they touch the graph. */
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
  /** Python class name → type label (e.g. "ManagerAgent" → "Planner/Orchestrator") */
  private classToType: Record<string, string> = {};

  // Persisted dropdown selection per AGENT_TYPE — proxied into state so it
  // survives navigation. Empty map = every chip defaults to its first
  // variant (the EvoMas built-in).
  get selectedVariantByType(): Record<string, string> {
    return this.svc.selectedVariantByType;
  }
  variantsFor(type: string): AgentVariant[] {
    return this.agentTypes.find(t => t.type === type)?.variants ?? [];
  }
  selectedVariantKey(type: string): string {
    const stored = this.selectedVariantByType[type];
    if (stored) return stored;
    const vs = this.variantsFor(type);
    return vs.length ? vs[0].key : `evomas:${type}`;
  }
  onVariantChange(type: string, key: string): void {
    this.selectedVariantByType[type] = key;
    this.cdr.markForCheck();
  }
  /** Resolve a variant.key to its full AgentVariant across every type's
   * variants list. Returns null when the key is unknown (e.g. a legacy
   * drag from before the picker existed). */
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
        // Build the class → type lookup with three families of keys so every
        // shape the JSON's `class` field can take resolves to a colored type:
        //   1. Python class name — `LocatorAgent`, `PatcherAgent`, …
        //   2. Type label itself — `Locator`, `Helper/Proxy`, … (used by
        //      type-driven configs like chain.json and openhands.json).
        const map: Record<string, string> = {};
        for (const t of types) {
          map[t.class] = t.type;
          map[t.type]  = t.type;
        }
        // LLMToolAgent is the generic config-driven base — color it as a Base agent.
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
    this.cy?.destroy();
  }

  private saveNodePositions(): void {
    const key = this.currentConfigName;
    if (!this.cy || !key) return;
    const positions: Record<string, { x: number; y: number }> = {};
    this.cy.nodes().forEach((n: NodeSingular) => {
      // Skip the virtual boundary nodes — their positions are derived from
      // the layout each render and don't belong in the per-config store.
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

  /** Resolve a node id to its human-readable label, falling back to the
   * raw node id when the agent-label catalog has no entry. Lives in the
   * component (rather than as a template-inline `??`) because TypeScript
   * types AGENT_LABELS as `Record<string, string>` — index access reads
   * as non-nullable in templates, which trips NG8102 on an inline `??`. */
  labelOrId(id: string): string {
    const base = this.baseAgentId(id);
    const labels = this.agentLabels as Record<string, string | undefined>;
    return labels[base] ?? id;
  }

  isPredefined(stem: string): boolean {
    return this.predefinedConfigs.some(c => c.stem === stem && c.source !== 'loaded');
  }

  /** Configs that ship with the framework — read-only. */
  get predefinedList(): ConfigSummary[] {
    return this.predefinedConfigs.filter(c => c.source !== 'loaded');
  }

  /** User-imported configs — renameable / deletable. */
  get loadedList(): ConfigSummary[] {
    return this.predefinedConfigs.filter(c => c.source === 'loaded');
  }

  /** Double-click to rename a loaded config. Predefined configs are
   * read-only — calling this on one is a no-op. */
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
        // Re-pull the list and re-load the renamed config so the graph stays
        // in sync with the new id.
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
            // Active config got deleted — fall back to the first predefined.
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

  private syncModelOptions(model: string): void {
    const base = this.svc.availableModels;
    if (model && !base.includes(model)) {
      this.modelSelectOptions = [model, ...base];
    } else {
      this.modelSelectOptions = [...base];
    }
  }

  /** Provider portion of an `<provider>/<model-id>` string. Unprefixed
   * legacy values (e.g. `qwen3.5:9b`) fall back to `ollama` to match
   * `evomas.models.parse_provider`'s backward-compat rule. */
  providerOf(model: string | undefined | null): 'ollama' | 'gemini' | 'openai' {
    const m = (model ?? '').trim().toLowerCase();
    if (m.startsWith('gemini/')) return 'gemini';
    if (m.startsWith('openai/')) return 'openai';
    return 'ollama';
  }

  /** Whether the current agent's provider honors a given hyperparameter.
   * Mirrors the per-provider builders in `evomas/models/`:
   *   - Ollama: every knob.
   *   - Gemini: temperature, top_p, top_k, num_predict, stream, stop.
   *   - OpenAI: temperature, top_p, num_predict, seed, stream, stop.
   * The template hides knobs that return false here so users don't tune
   * fields the provider would silently drop. */
  supportsKnob(knob: string): boolean {
    const p = this.providerOf(this.agentBlock?.model);
    if (p === 'ollama') return true;
    if (p === 'gemini') {
      return ['temperature', 'top_p', 'top_k', 'num_predict', 'stream', 'model'].includes(knob);
    }
    // openai
    return ['temperature', 'top_p', 'num_predict', 'seed', 'stream', 'model'].includes(knob);
  }

  /** Failure message shown in place of the graph when the backend can't
   * serve the requested config. Cleared on the next successful load. */
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
        // Drop the previous topology so the user doesn't think they're
        // still looking at the config they just clicked.
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
            // Auto-size to label with padding so long ids like
            // "Planner/Orchestrator" don't overflow the chip.
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
        // Conditional edge: an OrchestratorAgent source with ≥2 outgoing
        // edges → graph_builder installs `add_conditional_edges` with an
        // LLM-driven router. Render dashed in accent purple so it reads
        // as "the LLM picks at runtime".
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
        // Loop-back / cycle edge: identified by DFS as a back-edge
        // (target is on the recursion stack from the source). Render in
        // warning amber with an explicit curve (unbundled-bezier +
        // control point offset) so the back-edge visibly arcs around
        // the forward layout instead of overlapping it. The control-
        // point distance is signed per-edge via `data(cpd)` so the
        // arc flips side when the user drags one endpoint above the
        // other — keeps the curve on the "outside" of the layout.
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
        // Selection override for the two new edge classes — keep the
        // red selected color but preserve the dashed/curve traits that
        // identify the edge type.
        {
          selector: 'edge.edge-conditional:selected, edge.edge-loopback:selected',
          style: { 'line-color': '#f85149', 'target-arrow-color': '#f85149', width: 3 } as any,
        },
        // Virtual flow-boundary nodes (START / END). Distinct dashed-grey
        // pill so they read as control flow, not as agents. Not selectable;
        // tap handler ignores them outside of add-edge mode.
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
        // Virtual edges: dashed thin line so they read as derived /
        // boundary, not as a real agent transition.
        {
          selector: 'edge.virtual-edge',
          style: {
            width: 1.5,
            'line-color': '#6e7681',
            'target-arrow-color': '#6e7681',
            'line-style': 'dashed',
          } as any,
        },
        // Selected virtual edge: same red as a selected real edge so the
        // Delete action's affordance reads consistently.
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
            // Lay the BFS levels out left-to-right instead of top-to-bottom.
            // Linear chains (4 nodes) used to stack vertically and `cy.fit()`
            // would zoom out enough to make each node tiny; with a horizontal
            // flow the aspect ratio matches the wide viewport and nodes stay
            // readable. `transform` swaps x↔y on every laid-out node.
            transform: (_node: any, pos: any) => ({ x: pos.y, y: pos.x }),
          } as any,
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
      // Clamp the auto-zoom range so `cy.fit()` (used by Fit, Relayout, and
      // the post-layout fit in renderConfig) doesn't shrink the 11px node
      // labels below readability. Big graphs become panable instead.
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

    // One sync per cytoscape view event drives the parallax starfield,
    // the inline SVG world-space grid, and the zoom% readout. cytoscape
    // fires `pan` / `zoom` per RAF during interactive drags/wheel, and
    // `resize` when the host element's dimensions change (e.g. when the
    // left/right inspector boxes expand/collapse). One handler keeps
    // every dependent view in lock-step.
    const onView = () => this.zone.run(() => this.syncCyView());
    this.cy.on('pan', onView);
    this.cy.on('zoom', onView);
    this.cy.on('resize', onView);
    this.syncCyView();

    // Re-evaluate loop-back curve direction whenever an endpoint moves
    // so the arc flips side mid-drag if the user pulls one node above
    // or below the other. cytoscape's `position` event fires per RAF
    // tick during a drag, so the curve tracks live.
    this.cy.on('position', 'node', evt => this.refreshLoopbackCurves(evt.target));
  }

  /** Re-derive the signed `cpd` (control-point distance) for every
   * loop-back edge attached to `movedNode` (or every loop-back edge
   * when none is supplied, e.g. right after a render). Sign convention:
   * if the target sits ABOVE the source on screen (target.y < source.y),
   * bulge UP (negative); otherwise bulge DOWN. That keeps the arc on
   * the side opposite the natural forward-flow band — drag the cycle
   * target above the source and the curve flips automatically. */
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

  /** Walk `cfg.edges` from `cfg.entry` via DFS, marking edges whose target
   * is currently on the recursion stack — the canonical back-edge
   * detection. Returns a Set of "from-to" ids so the renderer can apply
   * the `.edge-loopback` class. Forward and cross edges are not flagged
   * (they don't create cycles in a DAG sense). */
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
    // Cover disconnected sub-graphs the entry can't reach. Any node
    // not yet visited gets its own DFS root.
    for (const id of Object.keys(cfg.agents)) {
      if (!visited.has(id)) dfs(id);
    }
    return back;
  }

  /** An edge is "conditional" when its source is an OrchestratorAgent
   * with ≥2 outgoing edges — matches graph_builder.py's `_make_router`
   * trigger so the visual marker tracks the runtime routing decision. */
  private isConditionalEdge(
    edge: { from: string; to: string },
    cfg: UnifiedConfig,
    outDegree: Record<string, number>,
  ): boolean {
    if ((outDegree[edge.from] ?? 0) < 2) return false;
    return cfg.agents[edge.from]?.class === 'OrchestratorAgent';
  }

  /** Normalize the `end` field on a config into a flat array of node ids.
   * Accepts a string ("manager_agent") or an array (["a", "b"]). The field
   * is part of the canonical schema; empty / missing → empty array. */
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
    // Explicit end declaration drives the virtual `?→END` edges. When the
    // config doesn't carry an `end` field, endNodeIds() falls back to leaf
    // detection (= backend's compat path) so the canvas still shows
    // boundaries for legacy JSONs.
    const endIds = new Set(this.endNodeIds(cfg));

    const startPos = savedPos[START_NODE_ID];
    const endPos   = savedPos[END_NODE_ID];
    const elements: cytoscape.ElementDefinition[] = [
      // Virtual START boundary node — display only, not selectable. Its
      // outgoing edge points at `cfg.entry`.
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
      // Virtual END boundary node.
      {
        data: { id: END_NODE_ID, label: 'END' },
        classes: 'virtual-node end-node',
        selectable: false,
        ...(endPos ? { position: { x: endPos.x, y: endPos.y } } : {}),
      },
      // Sort edges before handing them to cytoscape: the breadthfirst
      // layout orders sibling targets by the edge insertion order, so a
      // deterministic sort gives a deterministic layout (re-clicking
      // Relayout always produces the same shape).
      //
      // Edge classification: back-edges via DFS (visualised as amber
      // loop-back arcs) and conditional edges from OrchestratorAgent
      // sources with ≥2 outgoing edges (purple dashed). Loop-back wins
      // when both apply — a cycle dispatch is the cycle, not the route.
      ...(() => {
        const backEdges = this.findBackEdges(cfg);
        const outDegree: Record<string, number> = {};
        for (const e of cfg.edges) outDegree[e.from] = (outDegree[e.from] ?? 0) + 1;
        return [...cfg.edges]
          .sort((a, b) => (a.from === b.from ? a.to.localeCompare(b.to) : a.from.localeCompare(b.from)))
          .map(e => {
            const id = `${e.from}-${e.to}`;
            const classes: string[] = [];
            const data: Record<string, unknown> = { id, source: e.from, target: e.to };
            if (backEdges.has(id)) {
              classes.push('edge-loopback');
              // Seed `cpd` with a placeholder positive value; the
              // `position` handler / post-render call to
              // refreshLoopbackCurves re-evaluates the sign once
              // positions are known.
              data['cpd'] = [70];
            } else if (this.isConditionalEdge(e, cfg, outDegree)) {
              classes.push('edge-conditional');
            }
            return { data, ...(classes.length ? { classes: classes.join(' ') } : {}) };
          });
      })(),
      // Virtual START → entry edge (only if `cfg.entry` resolves to an agent).
      // Selectable so the user can delete it to clear `cfg.entry`.
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
      // Virtual ?→END edges, one per node listed in `cfg.end`. Mirrors the
      // backend's `end` semantic in graph_builder.py. Selectable so the user
      // can delete an edge to remove its source from `cfg.end`.
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
            // Lay the BFS levels out left-to-right instead of top-to-bottom.
            // Linear chains (4 nodes) used to stack vertically and `cy.fit()`
            // would zoom out enough to make each node tiny; with a horizontal
            // flow the aspect ratio matches the wide viewport and nodes stay
            // readable. `transform` swaps x↔y on every laid-out node.
            transform: (_node: any, pos: any) => ({ x: pos.y, y: pos.x }),
          } as any).run();
      }
      this.cy.fit(undefined, 30);
    }
    // Seed the signed `cpd` for every loop-back edge so the initial
    // render arcs the right way without waiting for a `position` event.
    this.refreshLoopbackCurves();
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
      // Virtual nodes carry no agent block — clicking them just clears any
      // prior selection so the right-hand panel returns to its empty hint.
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
    // Both real edges and virtual START → entry / X → END edges are now
    // selectable. Deleting a virtual edge clears `cfg.entry` or removes
    // X from `cfg.end` via deleteSelected (see below).
    this.selectedEdgeId = edge.id();
    this.selectedAgent = null;
    this.cdr.markForCheck();
  }

  /** Apply a user-drawn edge in add-edge mode, branching on which endpoint
   * (if any) is a virtual boundary node. Real edges go through the regular
   * persist path; START → X updates `cfg.entry`; X → END clears X's other
   * outgoing edges (with confirm) so X becomes a leaf. After every branch
   * we call refreshBoundaryEdges() so the canvas-side virtual edges stay
   * in sync with the canonical state. */
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
      // Toggle `source`'s membership in `cfg.end`. Outgoing edges are
      // independent — a node in `end` can still dispatch to other nodes
      // and decide between them and END at runtime via its `route(state)`.
      // Mutation lives in memory until Save -- no confirm needed.
      const ends = this.endNodeIds(this.currentConfig);
      const idx = ends.indexOf(source);
      if (idx >= 0) {
        ends.splice(idx, 1);
      } else {
        ends.push(source);
      }
      // Always serialize `end` as a list[str] once the user has touched it,
      // so the JSON shape is stable regardless of how it was originally
      // written (string vs list).
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
    this.markDirty();
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
    // Virtual edges (START → entry, leaf → END) are display-only — the
    // canonical config stores `entry` separately and the leaf rule is
    // implicit. Filter them out before serializing.
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
    // If the entry was deleted, drop the dangling pointer so renderConfig
    // doesn't try to draw a START → ghost edge.
    if (this.currentConfig.entry && !this.currentConfig.agents[this.currentConfig.entry]) {
      this.currentConfig.entry = '';
    }
    // Same hygiene for `end`: prune any deleted node out of the list.
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

  /** Treat the keyboard "Delete" / "Backspace" as a shortcut for the toolbar
   * Delete button — only when something is selected on the canvas and the
   * focus isn't inside a text input (so deletes inside fields keep working). */
  @HostListener('document:keydown', ['$event'])
  onKeyDown(ev: KeyboardEvent): void {
    if (ev.key !== 'Delete' && ev.key !== 'Backspace') return;
    const target = ev.target as HTMLElement | null;
    const tag = target?.tagName?.toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return;
    // Predefined configs are read-only — block the keyboard shortcut just
    // like the toolbar Delete button is disabled in that state.
    if (!this.isLoadedConfig) return;
    if (!this.cy || this.cy.$(':selected').length === 0) return;
    ev.preventDefault();
    this.deleteSelected();
  }

  deleteSelected(): void {
    if (!this.currentConfig) return;
    const selected = this.cy.$(':selected');
    if (!selected.length) return;

    // Virtual edges are now selectable. Deleting them is a metadata edit on
    // `currentConfig` (no real cytoscape edge to remove -- refreshBoundaryEdges
    // re-derives them after the underlying state changes). Process those
    // FIRST so the subsequent real-element removal sees a consistent set.
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

    // Now the real graph elements. The virtual nodes (START / END) are
    // marked selectable:false so they never land in `:selected`; the
    // filter is belt-and-braces.
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

  /** Rename the currently-selected node. Node ids are 1:1 with `cfg.agents`
   * keys AND with the runtime state slot keys (`state[self.name]`), so the
   * rename must (a) reject collisions with any existing node and (b) rewrite
   * every reference: `cfg.agents` key, `cfg.entry`, `cfg.end`, every edge
   * endpoint, the cytoscape node id, and the saved-position map. The
   * `prompts.route` / `state[]` fields don't reference other node ids so
   * they pass through untouched. */
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

    // 1) Rebuild the agents dict so the original key order is preserved
    //    (Object.fromEntries(Object.entries(...).map(...)) keeps insertion order).
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
    // 3) Snapshot the current cytoscape positions for EVERY node into the
    //    saved-positions store, then migrate the renamed node's slot. We
    //    snapshot first so the rebuild via renderConfig doesn't re-layout
    //    untouched nodes — those need to stay where the user put them.
    this.saveNodePositions();
    const posKey = this.currentConfigName;
    if (posKey && this.svc.nodePositions[posKey]?.[oldName]) {
      this.svc.nodePositions[posKey][newName] = this.svc.nodePositions[posKey][oldName];
      delete this.svc.nodePositions[posKey][oldName];
    }
    // 4) Cytoscape doesn't support renaming a node id in place. Rather than
    //    do an error-prone remove+re-add dance for one node, rebuild the
    //    whole canvas from the now-canonical config. `renderConfig` reuses
    //    the existing cy instance (clear + re-add) and reads positions out
    //    of the saved-positions store, so untouched nodes don't move.
    this.renderConfig(this.currentConfig);
    // Re-run the breadthfirst layout after the rebuild so the canvas
    // settles on a clean shape (renderConfig keeps stored positions when
    // they exist, but a rename is exactly the moment to refresh layout).
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
            // Lay the BFS levels out left-to-right instead of top-to-bottom.
            // Linear chains (4 nodes) used to stack vertically and `cy.fit()`
            // would zoom out enough to make each node tiny; with a horizontal
            // flow the aspect ratio matches the wide viewport and nodes stay
            // readable. `transform` swaps x↔y on every laid-out node.
            transform: (_node: any, pos: any) => ({ x: pos.y, y: pos.x }),
          } as any).run();
    // Fit the viewport to the new layout. Without this the previous
    // zoom level persists across relayout, which made nodes appear
    // small even though their pixel sizes hadn't changed. `cy.fit()` is
    // bounded by minZoom (0.65) so very wide graphs still stay readable.
    this.cy.fit(undefined, 40);
    this.saveNodePositions();
  }

  /** Hard-reload the topology page: tear down cytoscape, drop saved
   * positions, and re-fetch the active config from the backend so the
   * graph rebuilds via the same codepath as an F5. Manual recovery for
   * the case where switching configs (or returning from another route
   * while inference is busy) leaves the canvas in a stuck state — nodes
   * piled on top of each other, tap handlers not firing, etc. The
   * reason it's a separate button rather than auto-triggered: automatic
   * deferred passes empirically didn't catch every browser timing path,
   * so giving the user one click is more reliable. */
  reloadGraph(): void {
    const name = this.currentConfigName;
    if (!name) return;
    // Guard against silently losing in-flight edits. Reload re-fetches
    // from disk, so anything dirty + unsaved is wiped. Match the
    // `saveToDisk` confirm() pattern; bypass only when there are no
    // unsaved changes (or it's a read-only predefined config that
    // can't carry edits in the first place).
    if (this.isLoadedConfig && this.dirty) {
      if (!window.confirm(
        `Reload "${name}"? You have unsaved edits — these will be discarded ` +
        `and the on-disk version of the config will replace the current canvas.`
      )) return;
    }
    // Drop saved positions so the breadthfirst layout runs fresh.
    delete this.svc.nodePositions[name];
    // Clear selection so the right-hand pane doesn't dangle on a node
    // the rebuilt graph hasn't recreated yet.
    this.selectedAgent = null;
    this.selectedEdgeId = null;
    // Tear down cytoscape entirely (instance + event handlers). Setting
    // `this.cy` undefined forces renderConfig down the initCytoscape
    // branch, which re-creates the instance from scratch.
    this.cy?.destroy();
    this.cy = undefined as unknown as Core;
    // Re-fetch the config from the backend so any out-of-band edits
    // are picked up too — same codepath as a page reload.
    this.loadPredefined(name);
  }

  fitGraph(): void { this.cy?.fit(undefined, 40); }

  // ─── World-space view state (drives bg parallax + SVG grid) ────
  /** Live `cy.pan()` offset, mirrored to the `.bg-stack` CSS transform
   * AND to the inline SVG grid's world-space `<g transform>`. Updated
   * by `syncCyView` on every `cy.on('pan'|'zoom'|'resize')` tick. */
  bgPanX = 0;
  bgPanY = 0;
  /** Live `cy.zoom()`, used by `gridTransform` so the world-space SVG
   * grid scales with the graph (zoom in → grid tiles grow on screen). */
  cyZoomLevel = 1;
  /** Container pixel dimensions from `cy.width()` / `cy.height()`,
   * used by `visWorld` to size the grid-cover rects so they always
   * span exactly the visible region. */
  cyContainerW = 800;
  cyContainerH = 600;

  /** Transform for the SVG grid's world-space `<g>` — full graph pan
   * + zoom, no division. Matches cytoscape's own world: a world-coord
   * point (0,0) lands at screen coord (bgPanX, bgPanY); world (W,H)
   * lands at (bgPanX + W*zoom, bgPanY + H*zoom). Means the dots +
   * crosses pan and zoom WITH the graph, not against it. */
  get gridTransform(): string {
    return `translate(${this.bgPanX} ${this.bgPanY}) scale(${this.cyZoomLevel})`;
  }

  /** Visible region of the world, in world coordinates. The grid-
   * cover rects use this to span exactly what's on screen — bigger
   * when zoomed out, smaller when zoomed in, offset by the inverse
   * pan so it always tracks the viewport. */
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

  /** In-canvas zoom controls. Multiplicative step is the convention from
   * cytoscape's wheel handler (1.2x per click feels natural to the eye). */
  zoomIn(): void { this.stepZoom(1.2); }
  zoomOut(): void { this.stepZoom(1 / 1.2); }

  private stepZoom(factor: number): void {
    if (!this.cy) return;
    const next = this.cy.zoom() * factor;
    const min = this.cy.minZoom();
    const max = this.cy.maxZoom();
    const clamped = Math.min(max, Math.max(min, next));
    // Anchor the zoom around the canvas center so the user keeps their
    // visual context (vs. cy.zoom(level) alone, which anchors around 0,0).
    const w = this.cy.width();
    const h = this.cy.height();
    this.cy.zoom({ level: clamped, renderedPosition: { x: w / 2, y: h / 2 } });
  }

  // ─── Drag from palette ─────────────────────────────────────────
  // (palette-chip drag-start is owned by `evo-agent-type-picker` now;
  //  this component only handles dragover + drop on the canvas.)

  onGraphDragOver(event: DragEvent): void {
    event.preventDefault();
    event.dataTransfer!.dropEffect = 'copy';
  }

  onGraphDrop(event: DragEvent): void {
    event.preventDefault();
    if (!this.isLoadedConfig) return;
    const type = event.dataTransfer?.getData('agent-type');
    if (!type || !this.cy || !this.currentConfig) return;
    // New optional payload: which variant (EvoMas built-in vs a CSV-derived
    // alternative) to seed the dropped node with. Falls back to the
    // built-in when missing (legacy drag from before the picker existed).
    const variantKey = event.dataTransfer?.getData('agent-variant') || '';
    const variant = variantKey ? this.findVariant(variantKey) : null;

    const rect = this.graphEl.nativeElement.getBoundingClientRect();
    const pan = this.cy.pan();
    const zoom = this.cy.zoom();
    const modelX = (event.clientX - rect.left - pan.x) / zoom;
    const modelY = (event.clientY - rect.top - pan.y) / zoom;

    const taken = new Set(Object.keys(this.currentConfig.agents));
    // Variant-driven base name. Both branches prefix the repo so the id is
    // self-documenting:
    //   EvoMas built-in -> `evomas_<type>` (e.g. `evomas_locator`).
    //   Repo variant    -> `<repo>_<agent_name>` (e.g. `aider_coder`).
    // Collisions get an automatic `_<n>` suffix via suggestNodeId; no prompt.
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
    // Newly added node has no outgoing edges → it should immediately show a
    // virtual leaf-to-END edge so the user sees its boundary status.
    this.refreshBoundaryEdges();
    this.markDirty();
  }

  getAgentColorStyle(agent: string): string {
    return this.colorForAgentNode(agent);
  }

  /** Resolve the color for a graph node by looking up its block's class via the
   * loaded agent-type catalog. Falls back to the legacy node-id palette while
   * the catalog is loading. */
  private colorForAgentNode(nodeId: string): string {
    const cls = this.currentConfig?.agents?.[nodeId]?.class ?? '';
    const type = this.classToType[cls];
    if (type && this.typeColor[type]) return this.typeColor[type];
    return AGENT_COLORS[this.baseAgentId(nodeId)] ?? '#888';
  }

  private defaultAgentBlock(type: string, variant?: AgentVariant | null): AgentBlock {
    // Pull the type's full default block from the catalog loaded by
    // /api/agent-types so a fresh node inherits the same prompts, tool list,
    // and Ollama hyperparameters that the backend would seed it with anyway.
    const meta = this.agentTypes.find(t => t.type === type);
    const cfg = (meta?.default_config ?? {}) as Record<string, unknown>;
    // A non-default variant overrides the prompts + tool list (config knobs
    // come from the canonical type defaults — repo variants don't carry
    // model hyperparameters, only the prompts the upstream repo authored).
    const useVariant = variant && variant.repo !== 'evomas';
    const variantTools = useVariant ? (variant?.default_tools ?? []) : (meta?.default_tools ?? []);
    const block: AgentBlock = {
      class: type,
      variant: variant?.key ?? `evomas:${type}`,
      // Sensible Ollama-side fallbacks if the type didn't ship a value for
      // a given knob — mirror the AgentConfig pydantic defaults.
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

  /** True when the active config came from evomas/config/loaded/ — only
   * loaded configs are writable from the topology page. Predefined ones
   * are read-only; users keep variants by exporting + re-importing. */
  get isLoadedConfig(): boolean {
    if (!this.currentConfigName) return false;
    return this.predefinedConfigs.some(
      c => c.stem === this.currentConfigName && c.source === 'loaded',
    );
  }

  /** Persist the in-memory config back to evomas/config/loaded/<stem>.json,
   * overwriting whatever was on disk. Save is destructive — there's no
   * on-disk history to recover from — so we hit a confirm() first, same
   * pattern as the loaded-config delete button. */
  saveToDisk(): void {
    if (!this.currentConfig || !this.currentConfigName) return;
    if (!this.isLoadedConfig) return;
    // Pre-flight validation: surface findings as a non-blocking warning
    // panel so the user can iterate freely. The save still proceeds; the
    // runtime is the authoritative gate when the user actually hits Run.
    const { errors, warnings } = this.validateConfig();
    this.validationErrors = errors;
    this.validationWarnings = warnings;
    if (!window.confirm(
      `Overwrite evomas/config/loaded/${this.currentConfigName}.json with the current edits? The previous file will be gone.`
    )) return;
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
    // Non-EvoMas variants explicitly carry their own (possibly empty) tool
    // list; skip the type-default fallback so the variant's data wins.
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

  /** Copy the type's DEFAULT_TOOLS into the active block so subsequent
   * mutations (add/remove/edit) operate on a real array. No-op once the
   * block has its own tools or carries a non-EvoMas variant key (whose
   * explicit empty list must not be replaced by the built-in defaults). */
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

  /** Leading "(empty)" entry rendered above the grouped sections in the
   * "Add tool" dropdown. Picking it dismisses the popover without
   * adding anything — `addTool($event)` guards on truthiness so the
   * empty string is a no-op. */
  emptyToolOption: SelectOption[] = [{ value: '', label: '(empty)' }];

  /** Bucket `unusedToolNames` into one `<optgroup>` per owning repo —
   * the owner comes from the `repo` field that `/api/tools` attaches
   * to each `ToolDescriptor`. EvoMas-core helpers (the top-level
   * `evomas/tools/*.py` modules) come back tagged `"evomas"`; every
   * other tool carries its `evomas/tools/<repo>/` folder name.
   *
   * Empty groups are filtered out by `evo-select`. Order: `REPO_GROUP_ORDER`
   * entries first (currently just `evomas`), then remaining repos
   * alphabetically — a new bundle added on the backend lights up here
   * without a frontend change. */
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
    // If we were rendering the type's DEFAULT_TOOLS as a fallback, copy
    // them into the block first so the user's add lands on top of them
    // rather than silently replacing them.
    this.materializeDefaultTools();
    if (this.agentBlock.tools!.some(t => t.name === name)) return;
    this.agentBlock.tools!.push({ name, params: {} });
    this.markDirty();
    this.cdr.markForCheck();
  }

  removeTool(idx: number): void {
    if (!this.isLoadedConfig) return;
    // Same materialization path on remove — without it, removing a "ghost"
    // default tool would no-op against the empty block.tools array.
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
  /** Per-section collapse state for the right-hand Agent Config inspector.
   * Defaults to all-open so first-time users still see everything; the
   * toggle persists across node selections because this component (and
   * therefore these fields) outlives any single agent-block edit. */
  paramsOpen = true;
  toolsOpen = true;
  promptsOpen = true;

  // ─── Prompt editor ─────────────────────────────────────────────
  /** Which prompt slot is currently visible: '' = collapsed, otherwise key. */
  promptTab: 'system' | 'user' | 'proxy' | 'route' | '' = '';

  togglePromptTab(slot: 'system' | 'user' | 'proxy' | 'route'): void {
    this.promptTab = this.promptTab === slot ? '' : slot;
  }

  /** Resolve the AgentType (live catalog from /api/agent-types) for the
   * currently-selected agent block. The lookup goes block.class → type
   * label via classToType, then type label → AgentType via agentTypes.
   * Used to surface the type's DEFAULT_SYSTEM / DEFAULT_USER / DEFAULT_TOOLS
   * when the block itself doesn't override them — that's how chain.json's
   * agents (which intentionally have no prompts/tools) inherit sensible
   * defaults. */
  get currentAgentType(): AgentType | null {
    const cls = this.agentBlock?.class;
    if (!cls) return null;
    const typeName = this.classToType[cls] ?? cls;
    return this.agentTypes.find(t => t.type === typeName) ?? null;
  }

  getPrompt(slot: 'system' | 'user' | 'proxy' | 'route'): string {
    const explicit = this.agentBlock?.prompts?.[slot];
    if (typeof explicit === 'string' && explicit.length > 0) return explicit;
    // Non-EvoMas variant: an empty slot is intentional (the upstream repo's
    // CSV row had no prompt of that type). Skip the built-in fallback.
    if (this.blockHasRepoVariant) return '';
    // No prompts in the block — fall back to the type's defaults so the
    // user sees what the agent will actually use at runtime.
    const t = this.currentAgentType;
    if (slot === 'system') return t?.default_system ?? '';
    if (slot === 'user')   return t?.default_user ?? '';
    return '';
  }

  onPromptChange(slot: 'system' | 'user' | 'proxy' | 'route', value: string): void {
    if (!this.isLoadedConfig) return;
    const block = this.agentBlock;
    if (!block) return;
    if (!block.prompts) block.prompts = {};
    block.prompts[slot] = value;
    this.markDirty();
  }

  // ─── Validation ────────────────────────────────────────────────
  /** Errors from the last validate() / saveToDisk() pass. Empty when the
   * config is structurally valid (or no validation has run yet). The
   * runtime `evomas/core/workflow/graph_builder.py` enforces all these
   * checks again, but at that point the user has already kicked off a
   * full inference run — Validate is the pre-flight surface. */
  validationErrors: string[] = [];
  /** Soft-fail diagnostics — graph still compiles, but the runtime
   * would log them. Rendered in a separate yellow panel below the
   * error panel. Cleared via `dismissValidationWarnings()`. */
  validationWarnings: string[] = [];
  validateFlash = false;

  /** Returns `{ valid, errors, warnings }` for `currentConfig`. Pure —
   * no side effects, so it's safe to call from both `validate()` (user
   * click) and `saveToDisk()` (silent pre-save block).
   *
   * Errors block graph compilation at runtime (graph_builder raises);
   * warnings don't — they surface things the runtime would log but
   * still allow (e.g. nodes unreachable from entry). */
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

    // 4 + 5. Shape diagnostics. `build_graph` no longer raises on
    //         either of these — the runtime tolerates them but runs
    //         degrade: orphan dead-ends stall the LangGraph branch that
    //         reaches them; disconnected nodes are pure dead weight.
    //         Both go into `warnings` so the user sees them without
    //         being blocked, and we DEDUPE: a fully-disconnected node
    //         would trip both rules — keep only the more specific
    //         "disconnected" message.
    const hasOutgoing = new Set<string>(cfg.edges.map(e => e.from));
    const hasIncoming = new Set<string>(cfg.edges.map(e => e.to));
    const endSet = new Set(ends);
    for (const id of agentIds) {
      const incoming = hasIncoming.has(id);
      const outgoing = hasOutgoing.has(id);
      const isEntry  = cfg.entry === id;
      const inEnd    = endSet.has(id);
      if (!incoming && !outgoing && !isEntry) {
        // Rule 5 — fully disconnected (covers rule 4's superset for this node).
        warnings.push(
          `Node "${id}" is disconnected — no incoming or outgoing edges and not the entry. ` +
          `It will never execute at runtime.`,
        );
      } else if (!outgoing && !inEnd) {
        // Rule 4 — has incoming edges but no exit and not in `end`.
        // Real runtime hazard: whichever branch reaches this node hangs
        // there until the recursion-limit kicks in.
        warnings.push(
          `Node "${id}" has no outgoing edges and is not in \`end\` — it's an orphan ` +
          `dead-end. The branch that reaches it will stall until the runtime ` +
          `recursion-limit aborts the run.`,
        );
      }
    }

    // 6. BFS from `entry` over `cfg.edges` must reach at least one
    //    degree-0 end-set node. Mirrors `graph_builder._build_graph()` —
    //    only nodes that are in `end` AND have no outgoing edges get the
    //    static `→ END` wire at runtime, so reaching an end-set node with
    //    out-edges still doesn't terminate the graph. Skipped when an
    //    earlier rule already marked `entry` or `end` malformed (the BFS
    //    would just be noise on top of a real problem).
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
    // Clear the "unvalidated" flag whether or not findings were surfaced —
    // the user has now acknowledged the diagnostics. Save unblocks even
    // when errors are visible (the user is choosing to bypass).
    this.svc.validated = true;
    // Flash green only when there's NOTHING to surface — neither hard
    // errors nor warnings. Warnings are non-fatal but worth eyeballing.
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
