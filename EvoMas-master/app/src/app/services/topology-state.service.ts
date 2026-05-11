import { Injectable } from '@angular/core';
import { Subject } from 'rxjs';
import { AgentBlock, ConfigSummary, UnifiedConfig } from '../models/types';

/**
 * Single source of truth for the in-memory unified config currently being viewed
 * and edited. Edits to a *loaded* config are persisted through the topology
 * page's Save button (POST /api/configs/loaded with replace=true). Predefined
 * configs are read-only — to keep an edited variant, export it via the brand
 * menu's Export config… and re-import it as a loaded config.
 */
@Injectable({ providedIn: 'root' })
export class TopologyStateService {
  // List of predefined configs available from the backend.
  // Each entry carries both the file `stem` (routing key) and the human `id`
  // (display label, sourced from the JSON's top-level `id` field).
  predefinedConfigs: ConfigSummary[] = [];

  // Currently loaded config (may have unsaved in-memory edits — only writable
  // when the active config came from evomas/config/loaded/).
  currentConfig: UnifiedConfig | null = null;
  // Display name (from currentConfig.name, or filename when opened from disk)
  currentConfigName: string | null = null;

  // Selection state
  selectedAgent: string | null = null;
  selectedEdgeId: string | null = null;

  // Available LLM models (populated from /api/models)
  availableModels: string[] = [];
  modelSelectOptions: string[] = [];

  // UI flags
  addEdgeMode = false;

  // Persisted node positions per config name
  nodePositions: Record<string, Record<string, { x: number; y: number }>> = {};

  // Notifies subscribers when currentConfig is replaced (e.g. by Open file).
  readonly configChanged = new Subject<UnifiedConfig | null>();

  setCurrentConfig(config: UnifiedConfig | null, displayName: string | null): void {
    this.currentConfig = config;
    this.currentConfigName = displayName;
    this.selectedAgent = null;
    this.selectedEdgeId = null;
    this.configChanged.next(config);
  }

  /** Block for the currently selected agent, or null. */
  selectedAgentBlock(): AgentBlock | null {
    if (!this.currentConfig || !this.selectedAgent) return null;
    return this.currentConfig.agents[this.selectedAgent] ?? null;
  }
}
