import { Injectable } from '@angular/core';
import { Subject } from 'rxjs';
import { AgentBlock, ConfigSummary, OllamaModel, UnifiedConfig } from '../models/types';
import type { SelectOption } from '../components/select/evo-select.component';

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

  // Available LLM models (populated from /api/models). Each entry
  // carries a `pulled` flag — pulled-locally entries are listed first
  // by the backend, then unpulled catalog entries. The Inference page
  // runs `ollama pull` for unpulled entries before a run starts.
  availableModels: OllamaModel[] = [];
  // Dropdown options for the inspector's model picker. `value` is the
  // clean `<provider>/<model>` identifier (so `ngModel` round-trips
  // cleanly), `label` may carry a `· pull` suffix to flag unpulled
  // catalog entries. Built by `syncModelOptions()` so the list reflects
  // both the locally-pulled set AND any model the active block already
  // references (even if it's been removed from the registry catalog
  // mid-session).
  modelSelectOptions: SelectOption[] = [];

  // UI flags
  addEdgeMode = false;

  /** True when the active config has in-memory edits that haven't been
   * written to disk. Reset on `setCurrentConfig()` (switching configs)
   * and on a successful `saveToDisk` from the Topology page.
   * Drives the "unsaved" toolbar chip. */
  dirty = false;

  /** True when the active config has been validated since the last edit.
   * Fresh-loaded configs default to `validated: true` (the user hasn't
   * touched anything yet). Every site that calls `markDirty()` also
   * flips this to `false`; the Validate toolbar button flips it back to
   * `true` whether or not findings were surfaced — the user has at
   * least acknowledged the diagnostics. Save is disabled while this is
   * `false` so the user can't ship un-inspected edits. */
  validated = true;

  // Persisted node positions per config name
  nodePositions: Record<string, Record<string, { x: number; y: number }>> = {};

  // Persisted dropdown selection for each palette chip (one entry per
  // canonical AGENT_TYPE). Survives navigation away from the page. Empty
  // map = every chip defaults to the EvoMas built-in (first variant).
  selectedVariantByType: Record<string, string> = {};

  // Notifies subscribers when currentConfig is replaced (e.g. by Open file).
  readonly configChanged = new Subject<UnifiedConfig | null>();

  setCurrentConfig(config: UnifiedConfig | null, displayName: string | null): void {
    this.currentConfig = config;
    this.currentConfigName = displayName;
    this.selectedAgent = null;
    this.selectedEdgeId = null;
    this.dirty = false;
    // Fresh-loaded config starts validated — Save is enabled until the
    // user touches anything, mirroring the "no unsaved edits" baseline.
    this.validated = true;
    this.configChanged.next(config);
  }

  /** Block for the currently selected agent, or null. */
  selectedAgentBlock(): AgentBlock | null {
    if (!this.currentConfig || !this.selectedAgent) return null;
    return this.currentConfig.agents[this.selectedAgent] ?? null;
  }
}
