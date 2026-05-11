import {
  Component, OnInit, OnDestroy, AfterViewInit, HostListener,
  ElementRef, ViewChild, ChangeDetectorRef, NgZone,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import cytoscape, { Core, NodeSingular, EdgeSingular } from 'cytoscape';
import { ApiService } from '../../services/api.service';
import { TopologyStateService } from '../../services/topology-state.service';
import {
  AgentBlock, AgentTool, AgentType, ConfigSummary, ToolDescriptor, UnifiedConfig,
  AGENT_COLORS, AGENT_LABELS, ALL_AGENTS, suggestNodeId,
} from '../../models/types';
import {
  EvoButtonComponent, EvoSliderComponent, EvoSpinboxComponent, EvoBoxComponent,
  EvoSelectComponent, EvoSwitchComponent, EvoHelpPopoverComponent,
} from '../../components/index';

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

  get agentBlock(): AgentBlock | null { return this.svc.selectedAgentBlock(); }

  availableTools: ToolDescriptor[] = [];
  agentTypes: AgentType[] = [];
  /** type label → color */
  private typeColor: Record<string, string> = {};
  /** Python class name → type label (e.g. "ManagerAgent" → "Planner/Orchestrator") */
  private classToType: Record<string, string> = {};

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
        //   1. Python class name — `LocalizatorAgent`, `PatcherAgent`, …
        //   2. Type label itself — `Localizator`, `Helper/Proxy`, … (used by
        //      type-driven configs like the new star.json and openhands.json).
        //   3. Concrete star classes — `ManagerAgent`, `LocalizeAgent`, …
        const map: Record<string, string> = {};
        for (const t of types) {
          map[t.class] = t.type;
          map[t.type]  = t.type;
        }
        Object.assign(map, {
          ManagerAgent:    'Planner/Orchestrator',
          LocalizeAgent:   'Localizator',
          PatchAgent:      'Patcher',
          ValidateAgent:   'Reviewer',
          EnsemblerAgent:  'Helper/Proxy',
          LLMToolAgent:    'Base agent',
        });
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
        const star = summaries.find(s => s.stem === 'evo-star');
        this.loadPredefined((star ?? summaries[0]).stem);
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
      ],
      layout: skipLayout
        ? { name: 'preset' }
        : { name: 'breadthfirst', directed: true, padding: 50, spacingFactor: 1.4 } as any,
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
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
      ...cfg.edges.map(e => ({
        data: { id: `${e.from}-${e.to}`, source: e.from, target: e.to },
      })),
      // Virtual START → entry edge (only if `cfg.entry` resolves to an agent).
      ...(cfg.entry && cfg.agents[cfg.entry]
        ? [{
            data: {
              id: `${START_NODE_ID}-${cfg.entry}`,
              source: START_NODE_ID,
              target: cfg.entry,
            },
            classes: 'virtual-edge',
            selectable: false,
          }]
        : []),
      // Virtual ?→END edges, one per node listed in `cfg.end`. Mirrors the
      // backend's `end` semantic in graph_builder.py.
      ...nodeIds
        .filter(id => endIds.has(id))
        .map(id => ({
          data: {
            id: `${id}-${END_NODE_ID}`,
            source: id,
            target: END_NODE_ID,
          },
          classes: 'virtual-edge',
          selectable: false,
        })),
    ];

    if (!this.cy) {
      this.initCytoscape(elements, hasPositions);
    } else {
      this.cy.elements().remove();
      this.cy.add(elements);
      this.cy.resize();
      if (!hasPositions) {
        this.cy.layout({ name: 'breadthfirst', directed: true, padding: 50, spacingFactor: 1.4 } as any).run();
      }
      this.cy.fit(undefined, 30);
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
    // Virtual edges (START → entry, leaf → END) are derived from the config
    // — the user changes them by drawing through START / END in add-edge
    // mode, not by selecting + deleting.
    if (edge.hasClass('virtual-edge')) {
      this.selectedEdgeId = null;
      this.selectedAgent = null;
      this.cdr.markForCheck();
      return;
    }
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

    if (source === START_NODE_ID) {
      this.currentConfig.entry = target;
      this.refreshBoundaryEdges();
      return;
    }

    if (target === END_NODE_ID) {
      // Toggle `source`'s membership in `cfg.end`. Outgoing edges are
      // independent — a node in `end` can still dispatch to other nodes
      // and decide between them and END at runtime via its `route(state)`.
      const ends = this.endNodeIds(this.currentConfig);
      const idx = ends.indexOf(source);
      if (idx >= 0) {
        if (!window.confirm(`Remove "${source}" from end nodes? It will no longer route to END.`)) return;
        ends.splice(idx, 1);
      } else {
        if (!window.confirm(`Add "${source}" to end nodes? It will be allowed to route to END.`)) return;
        ends.push(source);
      }
      // Always serialize `end` as a list[str] once the user has touched it,
      // so the JSON shape is stable regardless of how it was originally
      // written (string vs list).
      this.currentConfig.end = ends;
      this.refreshBoundaryEdges();
      return;
    }

    const edgeId = `${source}-${target}`;
    if (this.cy.getElementById(edgeId).length > 0) return;
    this.cy.add({ data: { id: edgeId, source, target } });
    this.persistEdgesFromGraph();
    this.refreshBoundaryEdges();
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
        selectable: false,
      });
    }

    const endIds = new Set(this.endNodeIds(this.currentConfig));
    endIds.forEach(id => {
      if (this.cy.getElementById(id).length > 0) {
        this.cy.add({
          data: { id: `${id}-${END_NODE_ID}`, source: id, target: END_NODE_ID },
          classes: 'virtual-edge',
          selectable: false,
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
    // Virtual elements are marked `selectable: false`, so they shouldn't end
    // up in `:selected` — but the filter is a cheap belt-and-braces guard.
    const sel = this.cy.$(':selected').filter(el =>
      el.id() !== START_NODE_ID &&
      el.id() !== END_NODE_ID &&
      !el.hasClass('virtual-edge'),
    );
    if (!sel.length) return;
    const nodeIds = sel.nodes().map(n => n.id());
    const edgeCount = sel.edges().length;
    const summary = nodeIds.length
      ? `node ${nodeIds.length === 1 ? '"' + nodeIds[0] + '"' : '(' + nodeIds.length + ')'}` +
        (edgeCount ? ` plus ${edgeCount} attached edge(s)` : '')
      : `${edgeCount} edge(s)`;
    if (!window.confirm(`Delete ${summary}? This cannot be undone.`)) return;
    sel.remove();
    this.persistNodesFromGraph();
    this.refreshBoundaryEdges();
    this.selectedAgent = null;
    this.selectedEdgeId = null;
  }


  relayout(): void {
    if (!this.cy) return;
    if (this.currentConfigName) delete this.svc.nodePositions[this.currentConfigName];
    this.cy.layout({ name: 'breadthfirst', directed: true, padding: 50, spacingFactor: 1.4 } as any).run();
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

  // ─── Drag from palette ─────────────────────────────────────────
  onPaletteDragStart(event: DragEvent, type: string): void {
    event.dataTransfer!.setData('agent-type', type);
    event.dataTransfer!.effectAllowed = 'copy';
  }

  onGraphDragOver(event: DragEvent): void {
    event.preventDefault();
    event.dataTransfer!.dropEffect = 'copy';
  }

  onGraphDrop(event: DragEvent): void {
    event.preventDefault();
    const type = event.dataTransfer?.getData('agent-type');
    if (!type || !this.cy || !this.currentConfig) return;

    const rect = this.graphEl.nativeElement.getBoundingClientRect();
    const pan = this.cy.pan();
    const zoom = this.cy.zoom();
    const modelX = (event.clientX - rect.left - pan.x) / zoom;
    const modelY = (event.clientY - rect.top - pan.y) / zoom;

    const taken = new Set(Object.keys(this.currentConfig.agents));
    // First drop of a type → use the literal type label as the node id (e.g.
    // "Base agent", "Helper/Proxy"). Subsequent drops prompt for a unique
    // name with a numbered suggestion.
    let id: string;
    if (!taken.has(type)) {
      id = type;
    } else {
      const suggestion = suggestNodeId(type, taken);
      const userInput = window.prompt(
        `Name for the new ${type} node (already have one — pick a unique id)`,
        suggestion,
      );
      if (userInput === null) return;
      id = userInput.trim() || suggestion;
      if (taken.has(id)) {
        window.alert(`A node named "${id}" already exists.`);
        return;
      }
    }

    this.cy.add({
      data: { id, label: id, color: this.typeColor[type] ?? '#888' },
      position: { x: modelX, y: modelY },
    });
    this.currentConfig.agents[id] = this.defaultAgentBlock(type);
    // Newly added node has no outgoing edges → it should immediately show a
    // virtual leaf-to-END edge so the user sees its boundary status.
    this.refreshBoundaryEdges();
  }

  /** Type label backing the chip in the palette — falls back to the type itself. */
  paletteLabel(type: string): string { return type; }

  /** Whether a chip should appear used (greyed-out) — currently never, since
   * the same type can be dropped multiple times under different node names. */
  typeInGraph(_type: string): boolean { return false; }

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

  private defaultAgentBlock(type: string): AgentBlock {
    // Pull the type's full default block from the catalog loaded by
    // /api/agent-types so a fresh node inherits the same prompts, tool list,
    // and Ollama hyperparameters that the backend would seed it with anyway.
    const meta = this.agentTypes.find(t => t.type === type);
    const cfg = (meta?.default_config ?? {}) as Record<string, unknown>;
    const block: AgentBlock = {
      class: type,
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
      tools: (meta?.default_tools ?? []).map(name => ({ name, params: {} })),
      prompts: {
        system: meta?.default_system ?? '',
        user:   meta?.default_user   ?? '',
        proxy:  '',
      },
    };
    return block;
  }

  // Kept for legacy template compatibility — no longer actively wired.
  private classForAgent(_agent: string): string {
    return 'BaseAgent';
  }

  // ─── Agent block edit ──────────────────────────────────────────
  onAgentField<K extends keyof AgentBlock>(key: K, value: AgentBlock[K]): void {
    const block = this.agentBlock;
    if (!block) return;
    block[key] = value;
    if (key === 'model') this.syncModelOptions(value as string);
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
    if (!window.confirm(
      `Overwrite evomas/config/loaded/${this.currentConfigName}.json with the current edits? The previous file will be gone.`
    )) return;
    this.api.saveLoadedConfig(this.currentConfigName, this.currentConfig, true).subscribe({
      next: () => {
        this.saveError = '';
        this.saveFlash = true;
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

  get currentTools(): AgentTool[] {
    if (!this.agentBlock) return [];
    // When the JSON block doesn't carry an explicit `tools` array, surface
    // the type's DEFAULT_TOOLS as a read-only preview. The first add/remove
    // call materializes them into the block so subsequent edits behave the
    // way they always have.
    if (this.agentBlock.tools && this.agentBlock.tools.length > 0) {
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
   * block has its own tools. */
  private materializeDefaultTools(): void {
    if (!this.agentBlock) return;
    if (this.agentBlock.tools && this.agentBlock.tools.length > 0) return;
    const t = this.currentAgentType;
    this.agentBlock.tools = (t?.default_tools ?? []).map(name => ({ name, params: {} }));
  }

  /** Tool names in the registry that the current agent has not yet added. */
  get unusedToolNames(): string[] {
    const used = new Set(this.currentTools.map(t => t.name));
    return this.availableTools.map(t => t.name).filter(n => !used.has(n));
  }

  toolDescription(name: string): string {
    return this.availableTools.find(t => t.name === name)?.description ?? '';
  }

  addTool(name: string): void {
    if (!name || !this.agentBlock) return;
    // If we were rendering the type's DEFAULT_TOOLS as a fallback, copy
    // them into the block first so the user's add lands on top of them
    // rather than silently replacing them.
    this.materializeDefaultTools();
    if (this.agentBlock.tools!.some(t => t.name === name)) return;
    this.agentBlock.tools!.push({ name, params: {} });
    this.cdr.markForCheck();
  }

  removeTool(idx: number): void {
    // Same materialization path on remove — without it, removing a "ghost"
    // default tool would no-op against the empty block.tools array.
    this.materializeDefaultTools();
    if (!this.agentBlock?.tools) return;
    this.agentBlock.tools.splice(idx, 1);
    delete this.toolParamsDraft[idx];
    delete this.toolParamsError[idx];
    this.cdr.markForCheck();
  }

  /** Pretty-printed JSON the textarea is bound to. */
  paramsJson(idx: number): string {
    if (this.toolParamsDraft[idx] !== undefined) return this.toolParamsDraft[idx];
    const params = this.currentTools[idx]?.params ?? {};
    return Object.keys(params).length === 0 ? '{}' : JSON.stringify(params, null, 2);
  }

  onParamsInput(idx: number, value: string): void {
    this.toolParamsDraft[idx] = value;
    try {
      const parsed = value.trim() ? JSON.parse(value) : {};
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('must be a JSON object');
      }
      this.currentTools[idx].params = parsed as Record<string, unknown>;
      delete this.toolParamsError[idx];
    } catch (err) {
      this.toolParamsError[idx] = (err as Error).message;
    }
  }

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
   * when the block itself doesn't override them — that's how star.json's
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
    // No prompts in the block — fall back to the type's defaults so the
    // user sees what the agent will actually use at runtime.
    const t = this.currentAgentType;
    if (slot === 'system') return t?.default_system ?? '';
    if (slot === 'user')   return t?.default_user ?? '';
    return '';
  }

  onPromptChange(slot: 'system' | 'user' | 'proxy' | 'route', value: string): void {
    const block = this.agentBlock;
    if (!block) return;
    if (!block.prompts) block.prompts = {};
    block.prompts[slot] = value;
  }
}
