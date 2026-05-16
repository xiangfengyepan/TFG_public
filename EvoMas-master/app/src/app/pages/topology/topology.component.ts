/** Topology page shell. Owns cross-cutting state via TopologyStateService,
 * the active UnifiedConfig + selection, and the prompt/tool draft buffers;
 * composes five sub-components. The graph canvas owns cytoscape and emits
 * intents (node tapped, edge added, node dropped, …) — every mutation
 * happens here and bumps `renderSeq` so the canvas re-renders. */
import {
  Component, OnInit, OnDestroy, AfterViewInit,
  ChangeDetectorRef, NgZone, ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';

import { ApiService } from '../../services/api.service';
import { TopologyStateService } from '../../services/topology-state.service';
import {
  AgentBlock, AgentTool, AgentType, AgentVariant, ConfigSummary, ToolDescriptor,
  UnifiedConfig,
  AGENT_COLORS, AGENT_LABELS, ALL_AGENTS, normalizeNodeBase, suggestNodeId,
} from '../../models/types';
import { EvoAgentTypePickerComponent } from '../../components/index';

import {
  TopoLeftPaletteComponent, GraphToolbarComponent, ValidationPanelsComponent,
  GraphCanvasComponent, AgentInspectorComponent,
  SuperStep, SuperStepOutline, NodeDropPayload,
  START_NODE_ID, END_NODE_ID,
} from './components/index';

type PromptSlot = 'system' | 'user' | 'proxy' | 'route';

@Component({
  selector: 'app-topology',
  standalone: true,
  imports: [
    CommonModule, FormsModule, EvoAgentTypePickerComponent,
    TopoLeftPaletteComponent, GraphToolbarComponent, ValidationPanelsComponent,
    GraphCanvasComponent, AgentInspectorComponent,
  ],
  templateUrl: './topology.component.html',
  styleUrl: './topology.component.css',
})
export class TopologyComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild(GraphCanvasComponent) canvas!: GraphCanvasComponent;

  readonly allAgents = ALL_AGENTS;
  readonly agentColors = AGENT_COLORS;
  readonly agentLabels = AGENT_LABELS;

  availableTools: ToolDescriptor[] = [];
  agentTypes: AgentType[] = [];
  /** Bumped after every mutation so the canvas re-renders via ngOnChanges. */
  renderSeq = 0;

  /** type → color (driven by /api/agent-types). */
  typeColor: Record<string, string> = {};
  /** Python class name → type label. */
  classToType: Record<string, string> = {};

  /** Failure message shown in place of the graph when the backend can't
   * serve the requested config. */
  loadError = '';

  saveFlash = false;
  saveError = '';
  validateFlash = false;
  validationErrors: string[] = [];
  validationWarnings: string[] = [];

  /** Per-block drafts for the JSON tool-params textareas, keyed by index. */
  toolParamsDraft: Record<number, string> = {};
  toolParamsError: Record<number, string> = {};
  promptTab: PromptSlot | '' = '';

  private configChangedSub?: Subscription;

  constructor(
    private api: ApiService,
    private svc: TopologyStateService,
    private cdr: ChangeDetectorRef,
    private zone: NgZone,
  ) {}

  // ─── State proxies ─────────────────────────────────────────────
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

  get dirty(): boolean { return this.svc.dirty; }
  get validated(): boolean { return this.svc.validated; }

  get agentBlock(): AgentBlock | null { return this.svc.selectedAgentBlock(); }

  get selectedVariantByType(): Record<string, string> { return this.svc.selectedVariantByType; }

  get predefinedList(): ConfigSummary[] { return this.predefinedConfigs.filter(c => c.source !== 'loaded'); }
  get loadedList(): ConfigSummary[] { return this.predefinedConfigs.filter(c => c.source === 'loaded'); }

  get isLoadedConfig(): boolean {
    if (!this.currentConfigName) return false;
    return this.predefinedConfigs.some(c => c.stem === this.currentConfigName && c.source === 'loaded');
  }

  get savedPositionsForCurrent(): Record<string, { x: number; y: number }> {
    const key = this.currentConfigName;
    if (!key) return {};
    return this.svc.nodePositions[key] ?? {};
  }

  get currentAgentType(): AgentType | null {
    const cls = this.agentBlock?.class;
    if (!cls) return null;
    const typeName = this.classToType[cls] ?? cls;
    return this.agentTypes.find(t => t.type === typeName) ?? null;
  }

  /** True when the active block came from a non-EvoMas variant (the
   * built-in defaults must not leak in as fallback). */
  private get blockHasRepoVariant(): boolean {
    const v = this.agentBlock?.variant;
    return !!v && !v.startsWith('evomas:');
  }

  get currentTools(): AgentTool[] {
    if (!this.agentBlock) return [];
    if (this.agentBlock.tools && this.agentBlock.tools.length > 0) return this.agentBlock.tools;
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

  get unusedToolNames(): string[] {
    const used = new Set(this.currentTools.map(t => t.name));
    return this.availableTools.map(t => t.name).filter(n => !used.has(n));
  }

  // ─── Helpers ──────────────────────────────────────────────────
  baseAgentId(id: string): string { return id.replace(/_\d+$/, ''); }
  labelOrId(id: string): string {
    const base = this.baseAgentId(id);
    const labels = this.agentLabels as Record<string, string | undefined>;
    return labels[base] ?? id;
  }

  isPredefined(stem: string): boolean {
    return this.predefinedConfigs.some(c => c.stem === stem && c.source !== 'loaded');
  }

  variantsFor = (type: string): AgentVariant[] => {
    return this.agentTypes.find(t => t.type === type)?.variants ?? [];
  };

  selectedVariantKey = (type: string): string => {
    const stored = this.selectedVariantByType[type];
    if (stored) return stored;
    const vs = this.variantsFor(type);
    return vs.length ? vs[0].key : `evomas:${type}`;
  };

  onVariantChange(type: string, key: string): void {
    this.selectedVariantByType[type] = key;
    this.cdr.markForCheck();
  }

  private findVariant(key: string): AgentVariant | null {
    for (const t of this.agentTypes) {
      const hit = (t.variants ?? []).find(v => v.key === key);
      if (hit) return hit;
    }
    return null;
  }

  private markDirty(): void {
    if (this.svc.dirty && !this.svc.validated) return;
    this.svc.dirty = true;
    this.svc.validated = false;
    this.cdr.markForCheck();
  }

  private bumpRender(): void {
    this.renderSeq++;
    // Imperative push so the canvas re-renders on the same tick — avoids
    // having to wait for Angular CD to propagate the @Input. Falls back
    // gracefully when the canvas isn't yet view-init'd (e.g. on first
    // load triggered before ngAfterViewInit).
    this.canvas?.rerender(this.currentConfig, this.savedPositionsForCurrent);
    this.cdr.markForCheck();
  }

  private endNodeIds(cfg: UnifiedConfig): string[] {
    if (typeof cfg.end === 'string') return cfg.end ? [cfg.end] : [];
    if (Array.isArray(cfg.end)) return cfg.end.filter(Boolean);
    return [];
  }

  agentBadgeColor(id: string | null): string {
    if (!id) return '#888';
    const cls = this.currentConfig?.agents?.[id]?.class ?? '';
    const type = this.classToType[cls];
    if (type && this.typeColor[type]) return this.typeColor[type];
    return AGENT_COLORS[this.baseAgentId(id)] ?? '#888';
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
        const map: Record<string, string> = {};
        for (const t of types) {
          map[t.class] = t.type;
          map[t.type]  = t.type;
        }
        map['LLMToolAgent'] = 'Base agent';
        this.classToType = map;
        this.bumpRender();
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

    this.configChangedSub = this.svc.configChanged.subscribe(cfg => {
      if (cfg) {
        this.zone.run(() => {
          this.syncModelOptions(this.agentBlock?.model ?? '');
          this.bumpRender();
        });
      }
    });

    this.reloadGraph();
  }

  ngAfterViewInit(): void { /* canvas handles its own init */ }

  ngOnDestroy(): void {
    this.configChangedSub?.unsubscribe();
  }

  // ─── Config picker ────────────────────────────────────────────
  loadPredefined(name: string): void {
    this.api.getConfig(name).subscribe({
      next: cfg => {
        this.loadError = '';
        this.svc.setCurrentConfig(cfg, name);
        this.bumpRender();
      },
      error: err => {
        this.svc.setCurrentConfig(null, name);
        const detail = err?.error?.detail ?? err?.message ?? 'unknown error';
        this.loadError = `Failed to load "${name}": ${detail}`;
        this.bumpRender();
      },
    });
  }

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
          if (this.currentConfigName === stem) this.loadPredefined(trimmed);
          this.cdr.markForCheck();
        });
      },
      error: err => {
        window.alert(`Rename failed: ${err?.error?.detail ?? err?.message ?? 'unknown error'}`);
      },
    });
  }

  deleteLoaded(payload: { stem: string; ev: Event }): void {
    payload.ev?.stopPropagation();
    const { stem } = payload;
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

  // ─── Toolbar handlers ─────────────────────────────────────────
  toggleAddEdgeMode(): void {
    this.addEdgeMode = !this.addEdgeMode;
    this.cdr.markForCheck();
  }

  validate(): void {
    const { valid, errors, warnings } = this.validateConfig();
    this.validationErrors = errors;
    this.validationWarnings = warnings;
    this.svc.validated = true;
    if (valid && warnings.length === 0) {
      this.validateFlash = true;
      setTimeout(() => { this.validateFlash = false; this.cdr.markForCheck(); }, 1500);
    }
    this.cdr.markForCheck();
  }

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

    const ends = this.endNodeIds(cfg);
    const outEdges: Record<string, string[]> = {};
    const inEdges:  Record<string, string[]> = {};
    for (const e of cfg.edges) {
      (outEdges[e.from] ||= []).push(e.to);
      (inEdges[e.to]   ||= []).push(e.from);
    }
    const endZeroDegree = ends.filter(id => !(outEdges[id]?.length));

    if (cfg.entry && cfg.agents[cfg.entry] && endZeroDegree.length > 0) {
      const fromStart = new Set<string>();
      const fwd = [cfg.entry];
      while (fwd.length) {
        const n = fwd.shift()!;
        if (fromStart.has(n)) continue;
        fromStart.add(n);
        for (const t of (outEdges[n] ?? [])) fwd.push(t);
      }
      const toEnd = new Set<string>();
      const bwd = [...endZeroDegree];
      while (bwd.length) {
        const n = bwd.shift()!;
        if (toEnd.has(n)) continue;
        toEnd.add(n);
        for (const s of (inEdges[n] ?? [])) bwd.push(s);
      }
      for (const id of agentIds) {
        if (!fromStart.has(id) || !toEnd.has(id)) {
          warnings.push(
            `Node "${id}" is not on any path from START → END — it will never ` +
            `execute at runtime. Either connect it into a path that reaches a ` +
            `degree-0 end-set node, or remove it from \`agents\`.`,
          );
        }
      }
    }

    return { valid: errors.length === 0, errors, warnings };
  }

  saveToDisk(): void {
    if (!this.currentConfig || !this.currentConfigName) return;
    if (!this.isLoadedConfig) return;
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

  fitGraph(): void { this.canvas?.fit(); }

  relayout(): void {
    if (this.currentConfigName) delete this.svc.nodePositions[this.currentConfigName];
    this.canvas?.relayout();
  }

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
    this.canvas?.destroyAndClear();
    this.loadPredefined(name);
  }

  dismissValidationErrors(): void { this.validationErrors = []; }
  dismissValidationWarnings(): void { this.validationWarnings = []; }

  // ─── Canvas intents ───────────────────────────────────────────
  onNodeSelected(id: string): void {
    this.selectedAgent = id;
    this.selectedEdgeId = null;
    this.syncModelOptions(this.agentBlock?.model ?? '');
    this.cdr.markForCheck();
  }

  onEdgeSelected(id: string): void {
    this.selectedEdgeId = id;
    this.selectedAgent = null;
    this.cdr.markForCheck();
  }

  onSelectionCleared(): void {
    this.selectedAgent = null;
    this.selectedEdgeId = null;
    this.cdr.markForCheck();
  }

  onAddEdgeModeChange(v: boolean): void {
    this.addEdgeMode = v;
    this.cdr.markForCheck();
  }

  onPositionsChanged(positions: Record<string, { x: number; y: number }>): void {
    const key = this.currentConfigName;
    if (!key) return;
    this.svc.nodePositions[key] = positions;
  }

  onEdgeAdded(payload: { source: string; target: string }): void {
    if (!this.currentConfig || !this.isLoadedConfig) return;
    const { source, target } = payload;

    if (source === START_NODE_ID) {
      this.currentConfig.entry = target;
      this.markDirty();
      this.bumpRender();
      return;
    }
    if (target === END_NODE_ID) {
      const ends = this.endNodeIds(this.currentConfig);
      const idx = ends.indexOf(source);
      if (idx >= 0) ends.splice(idx, 1);
      else ends.push(source);
      this.currentConfig.end = ends;
      this.markDirty();
      this.bumpRender();
      return;
    }

    const edgeId = `${source}-${target}`;
    if (this.currentConfig.edges.some(e => `${e.from}-${e.to}` === edgeId)) return;
    this.currentConfig.edges.push({ from: source, to: target });
    this.markDirty();
    this.bumpRender();
  }

  onNodeDropped(payload: NodeDropPayload): void {
    if (!this.isLoadedConfig || !this.currentConfig) return;
    const { type, variantKey, x, y } = payload;
    const variant = variantKey ? this.findVariant(variantKey) : null;

    const taken = new Set(Object.keys(this.currentConfig.agents));
    let base: string;
    if (variant && variant.repo !== 'evomas') {
      base = `${normalizeNodeBase(variant.repo)}_${normalizeNodeBase(variant.name || type)}`;
    } else {
      base = `evomas_${normalizeNodeBase(type)}`;
    }
    if (!base) base = normalizeNodeBase(type) || 'agent';
    const id = taken.has(base) ? suggestNodeId(base, taken) : base;

    this.currentConfig.agents[id] = this.defaultAgentBlock(type, variant);
    // Persist position so the canvas places the new node where dropped.
    const key = this.currentConfigName;
    if (key) {
      this.svc.nodePositions[key] = { ...(this.svc.nodePositions[key] ?? {}), [id]: { x, y } };
    }
    this.markDirty();
    this.bumpRender();
  }

  onRequestDelete(): void { this.deleteSelected(); }

  deleteSelected(): void {
    if (!this.currentConfig) return;
    const snap = this.canvas?.getSelectedSnapshot();
    if (!snap) return;
    // Virtual edges first: metadata edits on entry / end.
    for (const v of snap.virtualEdges) {
      if (v.source === START_NODE_ID) {
        this.currentConfig.entry = '';
      } else if (v.target === END_NODE_ID) {
        const ends = this.endNodeIds(this.currentConfig).filter(n => n !== v.source);
        this.currentConfig.end = ends;
      }
    }
    // Real ids: drop from agents + prune edges + entry/end references.
    if (snap.realIds.length > 0) {
      const dead = new Set(snap.realIds);
      for (const id of dead) delete this.currentConfig.agents[id];
      this.currentConfig.edges = this.currentConfig.edges.filter(
        e => !dead.has(e.from) && !dead.has(e.to),
      );
      if (this.currentConfig.entry && dead.has(this.currentConfig.entry)) {
        this.currentConfig.entry = '';
      }
      this.currentConfig.end = this.endNodeIds(this.currentConfig).filter(
        id => !dead.has(id),
      );
    }
    this.selectedAgent = null;
    this.selectedEdgeId = null;
    this.markDirty();
    this.bumpRender();
  }

  renameSelected(): void {
    if (!this.isLoadedConfig || !this.currentConfig) return;
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
      window.alert(`A node named "${newName}" already exists in this config. Pick a different name.`);
      return;
    }

    this.currentConfig.agents = Object.fromEntries(
      Object.entries(this.currentConfig.agents).map(
        ([k, v]) => [k === oldName ? newName : k, v],
      ),
    );
    if (this.currentConfig.entry === oldName) this.currentConfig.entry = newName;
    this.currentConfig.end = this.endNodeIds(this.currentConfig).map(n => n === oldName ? newName : n);
    for (const e of this.currentConfig.edges) {
      if (e.from === oldName) e.from = newName;
      if (e.to   === oldName) e.to   = newName;
    }
    const posKey = this.currentConfigName;
    if (posKey && this.svc.nodePositions[posKey]?.[oldName]) {
      this.svc.nodePositions[posKey][newName] = this.svc.nodePositions[posKey][oldName];
      delete this.svc.nodePositions[posKey][oldName];
    }
    this.selectedAgent = newName;
    this.markDirty();
    this.bumpRender();
    // After rerender, relayout for a clean shape (matches the original behavior).
    setTimeout(() => this.canvas?.relayout(), 0);
  }

  // ─── Inspector intents ────────────────────────────────────────
  onAgentField(payload: { key: keyof AgentBlock; value: AgentBlock[keyof AgentBlock] }): void {
    if (!this.isLoadedConfig) return;
    const block = this.agentBlock;
    if (!block) return;
    (block as any)[payload.key] = payload.value;
    if (payload.key === 'model') this.syncModelOptions(payload.value as string);
    this.markDirty();
    this.bumpRender();
  }

  addTool(name: string): void {
    if (!this.isLoadedConfig || !name || !this.agentBlock) return;
    this.materializeDefaultTools();
    if (this.agentBlock.tools!.some(t => t.name === name)) return;
    this.agentBlock.tools!.push({ name, params: {} });
    this.markDirty();
    this.cdr.markForCheck();
  }

  removeTool(idx: number): void {
    if (!this.isLoadedConfig) return;
    this.materializeDefaultTools();
    if (!this.agentBlock?.tools) return;
    this.agentBlock.tools.splice(idx, 1);
    delete this.toolParamsDraft[idx];
    delete this.toolParamsError[idx];
    this.markDirty();
    this.cdr.markForCheck();
  }

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

  paramsJson = (idx: number): string => {
    if (this.toolParamsDraft[idx] !== undefined) return this.toolParamsDraft[idx];
    const params = this.currentTools[idx]?.params ?? {};
    return Object.keys(params).length === 0 ? '{}' : JSON.stringify(params, null, 2);
  };

  onParamsInput(payload: { idx: number; value: string }): void {
    if (!this.isLoadedConfig) return;
    this.toolParamsDraft[payload.idx] = payload.value;
    try {
      const parsed = payload.value.trim() ? JSON.parse(payload.value) : {};
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('must be a JSON object');
      }
      this.currentTools[payload.idx].params = parsed as Record<string, unknown>;
      delete this.toolParamsError[payload.idx];
      this.markDirty();
    } catch (err) {
      this.toolParamsError[payload.idx] = (err as Error).message;
    }
  }

  togglePromptTab(slot: PromptSlot): void {
    this.promptTab = this.promptTab === slot ? '' : slot;
    this.cdr.markForCheck();
  }

  getPrompt = (slot: PromptSlot): string => {
    const explicit = this.agentBlock?.prompts?.[slot];
    if (typeof explicit === 'string' && explicit.length > 0) return explicit;
    if (this.blockHasRepoVariant) return '';
    const t = this.currentAgentType;
    if (slot === 'system') return t?.default_system ?? '';
    if (slot === 'user')   return t?.default_user ?? '';
    return '';
  };

  onPromptChange(payload: { slot: PromptSlot; value: string }): void {
    if (!this.isLoadedConfig) return;
    const block = this.agentBlock;
    if (!block) return;
    if (!block.prompts) block.prompts = {};
    block.prompts[payload.slot] = payload.value;
    this.markDirty();
  }

  toolDescription = (name: string): string => {
    return this.availableTools.find(t => t.name === name)?.description ?? '';
  };

  // ─── Knob support (per-provider) ─────────────────────────────
  providerOf(model: string | undefined | null): 'ollama' | 'gemini' | 'openai' {
    const m = (model ?? '').trim().toLowerCase();
    if (m.startsWith('gemini/')) return 'gemini';
    if (m.startsWith('openai/')) return 'openai';
    return 'ollama';
  }

  supportsKnob = (knob: string): boolean => {
    const p = this.providerOf(this.agentBlock?.model);
    if (p === 'ollama') return true;
    if (p === 'gemini') {
      return ['temperature', 'top_p', 'top_k', 'num_predict', 'stream', 'model'].includes(knob);
    }
    return ['temperature', 'top_p', 'num_predict', 'seed', 'stream', 'model'].includes(knob);
  };

  private syncModelOptions(model: string): void {
    const base = this.svc.availableModels;
    if (model && !base.includes(model)) {
      this.modelSelectOptions = [model, ...base];
    } else {
      this.modelSelectOptions = [...base];
    }
  }

  // ─── Super-step outline (drives the toolbar help popover) ────
  superStepOutline(): SuperStepOutline {
    const cfg = this.currentConfig;
    if (!cfg || !cfg.entry || !cfg.agents?.[cfg.entry]) {
      return { steps: [], empty: true };
    }
    const sortedEdges = [...(cfg.edges ?? [])].sort((a, b) =>
      a.from === b.from ? a.to.localeCompare(b.to) : a.from.localeCompare(b.from),
    );
    const outEdges: Record<string, string[]> = {};
    for (const e of sortedEdges) (outEdges[e.from] ||= []).push(e.to);

    const steps: SuperStep[] = [];
    const visited = new Set<string>();
    let frontier: string[] = [cfg.entry];
    const MAX_STEPS = 20;

    while (frontier.length > 0 && steps.length < MAX_STEPS) {
      const dedup = Array.from(new Set(frontier)).filter(n => cfg.agents[n]);
      if (dedup.length === 0) break;
      const allRevisited = dedup.every(n => visited.has(n));
      steps.push({
        step: steps.length + 1,
        nodes: dedup,
        note: allRevisited ? 'cycle — re-executes until `recursion_limit` is hit' : undefined,
      });
      if (allRevisited) break;
      dedup.forEach(n => visited.add(n));
      const next: string[] = [];
      for (const n of dedup) for (const t of (outEdges[n] ?? [])) next.push(t);
      if (next.length === 0) {
        steps.push({ step: steps.length + 1, nodes: ['END'] });
        break;
      }
      frontier = next;
    }
    return { steps, empty: false };
  }

  private defaultAgentBlock(type: string, variant?: AgentVariant | null): AgentBlock {
    const meta = this.agentTypes.find(t => t.type === type);
    const cfg = (meta?.default_config ?? {}) as Record<string, unknown>;
    const useVariant = variant && variant.repo !== 'evomas';
    const variantTools = useVariant ? (variant?.default_tools ?? []) : (meta?.default_tools ?? []);
    return {
      class: type,
      variant: variant?.key ?? `evomas:${type}`,
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
  }
}
