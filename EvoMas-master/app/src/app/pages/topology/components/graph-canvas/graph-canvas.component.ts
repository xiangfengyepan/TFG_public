/** Cytoscape host + drag/drop target + boundary virtual nodes. Owns the
 * `cy` instance and all cytoscape lifecycle; emits high-level intents
 * (node/edge selected, edge added, node dropped, positions changed) so
 * the parent can mutate the canonical UnifiedConfig. Re-renders on every
 * change of the `renderSeq` input — parent ticks it after any mutation. */
import {
  AfterViewInit, ChangeDetectorRef, Component, ElementRef, EventEmitter,
  HostListener, Input, NgZone, OnChanges, OnDestroy, Output, SimpleChanges,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import cytoscape, { Core, EdgeSingular, NodeSingular } from 'cytoscape';

import { AGENT_COLORS, AGENT_LABELS, UnifiedConfig } from '../../../../models/types';

export const START_NODE_ID = '__START__';
export const END_NODE_ID = '__END__';

export interface NodeDropPayload {
  type: string;
  variantKey: string;
  x: number;
  y: number;
}

@Component({
  selector: 'app-graph-canvas',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './graph-canvas.component.html',
  styleUrl: './graph-canvas.component.css',
})
export class GraphCanvasComponent implements AfterViewInit, OnChanges, OnDestroy {
  @ViewChild('graphEl') graphEl!: ElementRef<HTMLDivElement>;

  @Input() currentConfig: UnifiedConfig | null = null;
  @Input() currentConfigName: string | null = null;
  @Input() isLoadedConfig = false;
  @Input() addEdgeMode = false;
  @Input() savedPositions: Record<string, { x: number; y: number }> = {};
  @Input() typeColor: Record<string, string> = {};
  @Input() classToType: Record<string, string> = {};
  @Input() loadError = '';
  /** Parent ticks this counter after every mutation it makes to
   * currentConfig so the canvas re-renders. */
  @Input() renderSeq = 0;

  @Output() nodeSelected = new EventEmitter<string>();
  @Output() edgeSelected = new EventEmitter<string>();
  @Output() selectionCleared = new EventEmitter<void>();
  @Output() edgeAdded = new EventEmitter<{ source: string; target: string }>();
  @Output() nodeDropped = new EventEmitter<NodeDropPayload>();
  @Output() positionsChanged = new EventEmitter<Record<string, { x: number; y: number }>>();
  @Output() requestDelete = new EventEmitter<void>();
  @Output() addEdgeModeChange = new EventEmitter<boolean>();

  private cy!: Core;
  private edgeSource: string | null = null;

  constructor(private cdr: ChangeDetectorRef, private zone: NgZone) {}

  ngAfterViewInit(): void {
    this.initCytoscape([]);
    if (this.currentConfig) this.renderConfig(this.currentConfig);
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (!this.cy) return;
    // Re-render only on real structural changes — config swap (reference
    // change on `currentConfig`) or a parent-bumped `renderSeq` (drop,
    // delete, edge add, rename, ...). DO NOT re-render on `savedPositions`
    // changes: those fire when the user drags a node, and a re-render
    // would wipe+re-add the canvas, leaving the virtual START/END nodes
    // unpositioned (emitPositions deliberately omits them) and clamping
    // cy.fit() against minZoom so only the boundary stays visible. The
    // dragged position is already on screen — it just needs to persist.
    if (changes['renderSeq'] || changes['currentConfig']) {
      if (this.currentConfig) {
        this.renderConfig(this.currentConfig);
      } else {
        // Failed load / no config — drop whatever's on the canvas so the
        // user doesn't think they're still looking at the previous graph.
        this.cy.elements().remove();
      }
    }
  }

  ngOnDestroy(): void {
    this.cy?.destroy();
  }

  /** Public hook the parent uses when it needs to force-fit (Fit/Relayout). */
  fit(): void { this.cy?.fit(undefined, 40); }

  relayout(): void {
    if (!this.cy) return;
    this.cy.layout(this.breadthfirstLayout()).run();
    this.cy.fit(undefined, 40);
    this.emitPositions();
  }

  /** Public hook for the parent's reloadGraph(). */
  destroyAndClear(): void {
    this.cy?.destroy();
    this.cy = undefined as unknown as Core;
  }

  private breadthfirstLayout(): any {
    return {
      name: 'breadthfirst', directed: true, padding: 40, spacingFactor: 1.2,
      nodeDimensionsIncludeLabels: true,
      transform: (_node: any, pos: any) => ({ x: pos.y, y: pos.x }),
    };
  }

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
            'padding-left': '12px', 'padding-right': '12px',
            'padding-top': '6px', 'padding-bottom': '6px',
            'font-size': 11, 'font-weight': 'bold',
            'text-valign': 'center', 'text-halign': 'center',
          } as any,
        },
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
      layout: skipLayout ? { name: 'preset' } : this.breadthfirstLayout(),
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
      minZoom: 0.65,
      maxZoom: 2.5,
    });

    this.cy.on('tap', 'node', evt => this.zone.run(() => this.onNodeTap(evt.target)));
    this.cy.on('tap', 'edge', evt => this.zone.run(() => this.onEdgeTap(evt.target)));
    this.cy.on('tap', evt => {
      if (evt.target === (this.cy as any)) {
        this.zone.run(() => {
          if (this.addEdgeMode && this.edgeSource) {
            this.cy.getElementById(this.edgeSource).removeClass('edge-source');
            this.edgeSource = null;
          }
          this.selectionCleared.emit();
        });
      }
    });
    this.cy.on('dragfreeon', 'node', () => this.zone.run(() => this.emitPositions()));
  }

  private endNodeIds(cfg: UnifiedConfig): string[] {
    if (typeof cfg.end === 'string') return cfg.end ? [cfg.end] : [];
    if (Array.isArray(cfg.end)) return cfg.end.filter(Boolean);
    return [];
  }

  baseAgentId(id: string): string { return id.replace(/_\d+$/, ''); }

  private colorForAgentNode(nodeId: string): string {
    const cls = this.currentConfig?.agents?.[nodeId]?.class ?? '';
    const type = this.classToType[cls];
    if (type && this.typeColor[type]) return this.typeColor[type];
    return AGENT_COLORS[this.baseAgentId(nodeId)] ?? '#888';
  }

  private renderConfig(cfg: UnifiedConfig): void {
    const savedPos = this.savedPositions ?? {};
    const hasPositions = Object.keys(savedPos).length > 0;

    const nodeIds = Object.keys(cfg.agents);
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
      ...[...cfg.edges]
        .sort((a, b) => (a.from === b.from ? a.to.localeCompare(b.to) : a.from.localeCompare(b.from)))
        .map(e => ({ data: { id: `${e.from}-${e.to}`, source: e.from, target: e.to } })),
      ...(cfg.entry && cfg.agents[cfg.entry]
        ? [{
            data: { id: `${START_NODE_ID}-${cfg.entry}`, source: START_NODE_ID, target: cfg.entry },
            classes: 'virtual-edge',
          }]
        : []),
      ...nodeIds
        .filter(id => endIds.has(id))
        .map(id => ({
          data: { id: `${id}-${END_NODE_ID}`, source: id, target: END_NODE_ID },
          classes: 'virtual-edge',
        })),
    ];

    if (!this.cy) {
      this.initCytoscape(elements, hasPositions);
    } else {
      this.cy.elements().remove();
      this.cy.add(elements);
      this.cy.resize();
      if (!hasPositions) this.cy.layout(this.breadthfirstLayout()).run();
      this.cy.fit(undefined, 30);
    }
  }

  private onNodeTap(node: NodeSingular): void {
    const id = node.id();
    const isVirtual = id === START_NODE_ID || id === END_NODE_ID;

    if (this.addEdgeMode) {
      if (!this.edgeSource) {
        if (id === END_NODE_ID) return;
        this.edgeSource = id;
        node.addClass('edge-source');
      } else if (this.edgeSource !== id) {
        if (id === START_NODE_ID) return;
        this.edgeAdded.emit({ source: this.edgeSource, target: id });
        this.cy.getElementById(this.edgeSource).removeClass('edge-source');
        this.edgeSource = null;
        this.addEdgeModeChange.emit(false);
      }
      this.cdr.markForCheck();
      return;
    }

    if (isVirtual) {
      this.selectionCleared.emit();
      return;
    }

    this.nodeSelected.emit(id);
  }

  private onEdgeTap(edge: EdgeSingular): void {
    this.edgeSelected.emit(edge.id());
  }

  private emitPositions(): void {
    if (!this.cy) return;
    const positions: Record<string, { x: number; y: number }> = {};
    this.cy.nodes().forEach((n: NodeSingular) => {
      const id = n.id();
      if (id === START_NODE_ID || id === END_NODE_ID) return;
      const p = n.position();
      positions[id] = { x: p.x, y: p.y };
    });
    this.positionsChanged.emit(positions);
  }

  // ─── Drag-drop from palette ────────────────────────────────────
  onGraphDragOver(event: DragEvent): void {
    event.preventDefault();
    event.dataTransfer!.dropEffect = 'copy';
  }

  onGraphDrop(event: DragEvent): void {
    event.preventDefault();
    if (!this.isLoadedConfig) return;
    const type = event.dataTransfer?.getData('agent-type');
    if (!type || !this.cy || !this.currentConfig) return;
    const variantKey = event.dataTransfer?.getData('agent-variant') || '';

    const rect = this.graphEl.nativeElement.getBoundingClientRect();
    const pan = this.cy.pan();
    const zoom = this.cy.zoom();
    const x = (event.clientX - rect.left - pan.x) / zoom;
    const y = (event.clientY - rect.top - pan.y) / zoom;
    this.nodeDropped.emit({ type, variantKey, x, y });
  }

  @HostListener('document:keydown', ['$event'])
  onKeyDown(ev: KeyboardEvent): void {
    if (ev.key !== 'Delete' && ev.key !== 'Backspace') return;
    const target = ev.target as HTMLElement | null;
    const tag = target?.tagName?.toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return;
    if (!this.isLoadedConfig) return;
    if (!this.cy || this.cy.$(':selected').length === 0) return;
    ev.preventDefault();
    this.requestDelete.emit();
  }

  /** Currently-selected real ids and virtual edges. Parent reads these
   * synchronously when handling `requestDelete`. */
  getSelectedSnapshot(): { realIds: string[]; virtualEdges: { source: string; target: string }[] } {
    if (!this.cy) return { realIds: [], virtualEdges: [] };
    const selected = this.cy.$(':selected');
    const realIds: string[] = [];
    const virtualEdges: { source: string; target: string }[] = [];
    selected.forEach(el => {
      const id = el.id();
      if (id === START_NODE_ID || id === END_NODE_ID) return;
      if (el.isEdge() && el.hasClass('virtual-edge')) {
        virtualEdges.push({
          source: el.data('source') as string,
          target: el.data('target') as string,
        });
      } else {
        realIds.push(id);
      }
    });
    return { realIds, virtualEdges };
  }

  /** Force a redraw with the supplied config + positions. Imperative
   * counterpart of the ngOnChanges-driven re-render — used when the
   * parent has just mutated the canonical config and can't wait for
   * Angular's CD to propagate the input.
   *
   * Critically: does NOT short-circuit on `!this.cy`. The Reload toolbar
   * action tears the cytoscape instance down (via `destroyAndClear`) and
   * then re-fetches the config, expecting the next `rerender` call to
   * recreate cy from scratch. `renderConfig` already branches on
   * `!this.cy` → `initCytoscape(...)`, so just delegate. */
  rerender(
    cfg: UnifiedConfig | null = this.currentConfig,
    savedPositions: Record<string, { x: number; y: number }> = this.savedPositions,
  ): void {
    this.currentConfig = cfg;
    this.savedPositions = savedPositions;
    if (cfg) {
      this.renderConfig(cfg);
    } else if (this.cy) {
      this.cy.elements().remove();
    }
  }
}
