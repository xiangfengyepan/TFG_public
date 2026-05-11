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

export type SwebenchSubset = 'lite' | 'full' | 'verified';
export type SwebenchSplit = 'dev' | 'test' | 'train';

/** Splits actually shipped per subset on HuggingFace.
 * (Confirmed against the dataset cards as of 2026-05.) */
export const SUBSET_SPLITS: Record<SwebenchSubset, SwebenchSplit[]> = {
  lite:     ['dev', 'test'],
  full:     ['dev', 'test', 'train'],
  verified: ['test'],
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
    | 'status' | 'start' | 'agent_event' | 'thinking_chunk' | 'tool_call'
    | 'instance_start' | 'instance_done' | 'done' | 'error' | 'cancelled';
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
  tool?: string;
  args_preview?: string;
  result_preview?: string;
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
  type: string;          // e.g. "Localizator", "Patcher"
  color: string;         // hex
  description: string;
  class: string;         // backing Python class name (e.g. "LocalizatorAgent")
  /** Per-type defaults the frontend uses to seed a freshly-dropped node. */
  default_system: string;
  default_user: string;
  default_tools: string[];
  default_config: Record<string, unknown>;
}

// Snake-case fallback ID generator used when dropping a type chip onto the graph.
export function suggestNodeId(typeLabel: string, takenIds: Set<string>): string {
  const base = typeLabel
    .toLowerCase()
    .replace(/[\/\s]+/g, '_')
    .replace(/[^a-z0-9_]+/g, '');
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
