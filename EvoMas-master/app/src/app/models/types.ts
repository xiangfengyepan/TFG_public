export interface AgentConfig {
  model: string;
  think: boolean | string;
  num_ctx: number;
  stream: boolean;
  temperature: number;
  top_k: number;
  top_p: number;
  min_p: number;
  repeat_penalty: number;
  repeat_last_n: number;
  seed: number;
  num_predict: number;
  stop: string[];
  [key: string]: unknown;
}

export interface StateField {
  name: string;
  type: string;
  default?: unknown;
}

export interface TopoEdge {
  from: string;
  to: string;
}

export interface PromptBlock {
  system?: string;
  user?: string;
  proxy?: string;
  route?: string;
  [key: string]: string | undefined;
}

export interface AgentTool {
  name: string;
  params: Record<string, unknown>;
}

export interface AgentBlock extends AgentConfig {
  class: string;
  /** Variant key (e.g. "evomas:Locator" or "OpenHands:CodeActAgent")
   * recording which palette dropdown choice seeded this block. Optional,
   * for traceability only -- the runtime reads `prompts` + `tools` directly. */
  variant?: string;
  state?: StateField[];
  tools?: AgentTool[];
  prompts?: PromptBlock;
}

export interface ToolDescriptor {
  name: string;
  description: string;
  inputSchema: {
    type?: string;
    properties?: Record<string, { type?: string; description?: string; default?: unknown }>;
    required?: string[];
    [k: string]: unknown;
  };
}

export interface UnifiedConfig {
  id: string;
  description: string;
  entry: string;
  /** Node(s) that route to langgraph END. May be a single node name or a
   * list. Required in the canonical schema; legacy configs without it fall
   * back to leaf detection on the backend (with a deprecation warning). */
  end?: string | string[];
  edges: TopoEdge[];
  agents: Record<string, AgentBlock>;
}

export interface ConfigSummary {
  /** Filename stem (URL routing key, --config arg). */
  stem: string;
  /** Human-facing identifier from the JSON's `id` field. */
  id: string;
  description: string;
  /** Where on disk the config lives: predefined (read-only) or loaded
   * (user-imported, renameable / deletable). */
  source: 'predefined' | 'loaded';
}

export type SwebenchSubset = 'lite' | 'full' | 'verified' | 'custom';
export type SwebenchSplit = 'dev' | 'test' | 'train' | 'custom';

/** Splits actually shipped per subset on HuggingFace.
 * (Confirmed against the dataset cards as of 2026-05.) The synthetic
 * `custom/custom` group hosts user-added GitHub repos from the Inference
 * page's "Add custom GitHub repo" form. */
export const SUBSET_SPLITS: Record<SwebenchSubset, SwebenchSplit[]> = {
  lite:     ['dev', 'test'],
  full:     ['dev', 'test', 'train'],
  verified: ['test'],
  custom:   ['custom'],
};

export interface Instance {
  instance_id: string;
  repo: string;
  problem_statement: string;
  subset: SwebenchSubset;
  split: SwebenchSplit;
}

export interface InferenceEvent {
  type:
    | 'status' | 'start' | 'agent_event' | 'thinking_chunk' | 'response'
    | 'tool_call' | 'agent_input' | 'agent_tokens' | 'run_id'
    | 'instance_start' | 'instance_done' | 'done' | 'error' | 'cancelled'
    | 'handoff';
  message?: string;
  instance_id?: string;
  instance_ids?: string[];
  index?: number;        // 0-based position in the per-run instance queue
  total?: number;        // total instances in this run
  run_id?: string;       // <instance_id>-<timestamp>, links prediction ↔ evaluation
  config?: string;
  agent?: string;
  delta?: Record<string, unknown>;
  patch?: string;
  output_path?: string;
  traceback?: string;
  chunk?: string;
  // response event payload — full LLM response after streaming completes.
  content?: string;
  tool?: string;
  args_preview?: string;
  result_preview?: string;
  // agent_input event payload — predecessor outputs the agent received.
  inputs?: Record<string, unknown>;
  // agent_tokens event payload — per-agent cumulative LLM usage.
  input?: number;
  output?: number;
  // handoff event payload — one per outgoing edge after an agent runs.
  // `from`/`to` are agent node ids; `summary` is a short type+size string
  // for the chip face; `preview` is the truncated full payload for a
  // click-to-expand modal. `keys` lists every state-slot the producer
  // wrote on this step (usually just `[agent_name]`).
  from?: string;
  to?: string;
  summary?: string;
  preview?: string;
  keys?: string[];
  timestamp?: string;
}

/** Hand-off chip rendered between two agent cards on the inference page.
 * Built from a `handoff` InferenceEvent; one chip per outgoing edge. */
export interface HandoffChip {
  from: string;
  to: string;
  summary: string;   // 'list(2 items, ~25 B)'
  preview: string;   // full payload (16KB cap on the server)
  keys: string[];
  timestamp: string;
}

export interface EvalEvent {
  type: 'log' | 'group_start' | 'group_done' | 'done' | 'error';
  message?: string;
  returncode?: number;
  subset?: string;
  split?: string;
  run_id?: string;
  count?: number;
}

export interface ResultPredictionFile {
  path: string;
  name: string;
  mtime: number;
}

export interface ResultEvaluationDir {
  run_id: string;
  model: string;
  dir: string;
  mtime: number;
}

export interface PredictionGroup {
  subset: SwebenchSubset;
  split: SwebenchSplit;
  instance_ids: string[];
}

export interface PredictionInspection {
  path: string;
  name: string;
  run_id_base: string;
  total: number;
  groups: PredictionGroup[];
}

export interface ResultRun {
  run_id: string;
  timestamp: string | null;
  prediction: ResultPredictionFile | null;
  evaluation: ResultEvaluationDir | null;
  mtime: number;
}

export interface ResultInstance {
  instance_id: string;
  /** Canonical (first) source subset / split, derived from the local
   * swebench_instances cache. Defaults to lite/dev when the id isn't in
   * the cache. */
  subset: SwebenchSubset;
  split: SwebenchSplit;
  /** Every (subset, split) the instance belongs to, expanded through the
   * SWE-bench dataset hierarchy (Lite/Verified rows imply a matching Full
   * row). Drives the Results page's subset-grouped left panel. */
  memberships: { subset: SwebenchSubset; split: SwebenchSplit }[];
  predictions: ResultPredictionFile[];
  evaluations: ResultEvaluationDir[];
  runs: ResultRun[];
}

/** LLM token usage for one prediction, written by the API worker.
 *   input  = prompt + context tokens sent to the model
 *   output = generated (response) tokens
 *   total  = input + output
 * The fields are optional because legacy predictions (pre-feature) don't
 * carry them. */
export interface PredictionTokens {
  input: number;
  output: number;
  total: number;
}

export interface ResultPrediction {
  path: string;
  name: string;
  raw: string;
  data: {
    instance_id?: string;
    model_patch?: string;
    model_name_or_path?: string;
    tokens?: PredictionTokens;
    [k: string]: unknown;
  };
}

export interface ResultEvaluation {
  dir: string;
  report: Record<string, unknown>;
  patch: string;
  files: string[];
  /** Per-run folder (parent of the per-instance evaluation dir). Useful for
   * the Results page's "reveal in explorer" button. */
  run_dir: string;
  /** Top-level cross-model summary file (`<model>.<run_id>.json`). Empty
   * string when no summary has been written yet. */
  summary_path: string;
}

// ─── Agent types (live catalog from /api/agent-types) ──────────────
export interface AgentType {
  type: string;          // e.g. "Locator", "Patcher"
  color: string;         // hex
  description: string;
  class: string;         // backing Python class name (e.g. "LocatorAgent")
  /** Per-type defaults the frontend uses to seed a freshly-dropped node. */
  default_system: string;
  default_user: string;
  default_tools: string[];
  default_config: Record<string, unknown>;
  /** Variants for this canonical AGENT_TYPE: the EvoMas built-in first,
   * then every CSV-derived alternative from open-source SWE-bench solver
   * repos. Populated by the same `/api/agent-types` response. */
  variants?: AgentVariant[];
}

/** One row in an AGENT_TYPE bucket -- either the EvoMas built-in or a
 * CSV-derived alternative from `evomas/config/agent_types/*.json`. */
export interface AgentVariant {
  /** Stable id used as the drag payload; e.g. "evomas:Locator" or
   * "OpenHands:CodeActAgent". */
  key: string;
  /** Display string, e.g. "EvoMas · default" or "OpenHands · CodeActAgent". */
  label: string;
  /** Originating repo (`"evomas"` for the built-in; CSV stem otherwise). */
  repo: string;
  /** Upstream agent name within the repo, e.g. "CodeActAgent" or "Coder".
   * For built-ins this equals the AGENT_TYPE so the dropped-node id can
   * fall back to a stable `evomas_<type>` pattern. */
  name: string;
  /** Canonical AGENT_TYPE this variant belongs to. */
  agent_type: string;
  /** Source-code anchor in the upstream repo (empty for built-ins). */
  source_url: string;
  description: string;
  default_system: string;
  default_user: string;
  default_proxy: string;
  default_tools: string[];
  default_config: Record<string, unknown>;
}

/** Lower-snake-case a free-form label (AGENT_TYPE, variant name, ...) into
 * a safe node id base. Used by `suggestNodeId` for collision suffixing and
 * by the Topology drop handler to derive a fresh id directly. */
export function normalizeNodeBase(label: string): string {
  return label
    .toLowerCase()
    .replace(/[\/\s]+/g, '_')
    .replace(/[^a-z0-9_]+/g, '')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '');
}

// Snake-case fallback ID generator used when dropping a type chip onto the graph.
export function suggestNodeId(typeLabel: string, takenIds: Set<string>): string {
  const base = normalizeNodeBase(typeLabel) || 'agent';
  let i = 1;
  while (takenIds.has(`${base}_${i}`)) i += 1;
  return `${base}_${i}`;
}

// Legacy keyed-by-node-id colors. Kept as a fallback while the topology JSON
// transitions from concrete classes to type-driven palette decisions.
export const AGENT_COLORS: Record<string, string> = {
  manager_agent:   '#e3b341',
  localize_agent:  '#388bfd',
  patch_agent:     '#56d364',
  validate_agent:  '#db61a2',
  ensembler_agent: '#a371f7',
};

export const AGENT_LABELS: Record<string, string> = {
  manager_agent:   'Manager',
  localize_agent:  'Localize',
  patch_agent:     'Patch',
  validate_agent:  'Validate',
  ensembler_agent: 'Ensembler',
};

export const ALL_AGENTS = Object.keys(AGENT_COLORS);
