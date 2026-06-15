/* eslint-disable */
/*
 * Boot script injected into gephi-lite's index.html BEFORE the React bundle.
 * Reads ?repo=<id> and ?layout=<radial|hierarchical> from the URL,
 * writes 1.0_session (layout) into sessionStorage, and points gephi-lite
 * at the right pre-filtered GEXF via the ?file= URL parameter.
 *
 * The build script (deploy/build.ps1) replaces the placeholder tokens
 * below with real values at build time.
 */
(function () {
  "use strict";

  // ── Injected at build time ─────────────────────────────────────────────────
  var SESSIONS = {
    radial:        {
  "metrics": {},
  "layoutsParameters": {
    "script": {
      "script": [
        "<<Function",
        "function nodeCoordinates(id, attributes, index, graph) {\n  const type = attributes.node_type;\n\n  // ── Spacing constants ─────────────────────────────────────────────────────\n  const RING = 300;         // distance between rings (increase to spread out)\n  const ANGLE_FILL = 0.7;   // fraction of a sector used by siblings (0–1, increase to spread wider)\n\n  const R = {\n    repo:            RING * 1,\n    agent:           RING * 2,\n    agent_node:      RING * 3,  // Prometheus sub-nodes\n    prompt_of_agent: RING * 3,  // regular prompts share ring with agent_node\n    prompt_of_node:  RING * 4,  // Prometheus prompts one ring further out\n    tool:            RING * 5,\n  };\n\n  // ── Helpers ───────────────────────────────────────────────────────────────\n  const allNodes = graph.nodes();\n\n  function ofType(t) {\n    return allNodes.filter(n => graph.getNodeAttribute(n, 'node_type') === t);\n  }\n\n  function parent(nid) {\n    const ins = graph.inNeighbors(nid);\n    return ins.length > 0 ? ins[0] : null;\n  }\n\n  function childrenOfType(pid, t) {\n    return graph.outNeighbors(pid)\n      .filter(n => graph.getNodeAttribute(n, 'node_type') === t);\n  }\n\n  function polar(angle, radius) {\n    return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };\n  }\n\n  // Spread siblings evenly within a fraction of the sector angle.\n  // Returns the angle for selfId among its siblings.\n  function spreadAngle(baseAngle, siblings, selfId, fraction) {\n    const n = siblings.length;\n    if (n <= 1) return baseAngle;\n    const i = siblings.indexOf(selfId);\n    const arc = sectorAngle * fraction;\n    return baseAngle + (i / (n - 1) - 0.5) * arc;\n  }\n\n  // ── Sector geometry ───────────────────────────────────────────────────────\n  const repos = ofType('repo');\n  const TWO_PI = 2 * Math.PI;\n  const sectorAngle = TWO_PI / Math.max(repos.length, 1);\n\n  // Start at the top (-π/2) and go clockwise\n  function repoAngle(rid) {\n    return repos.indexOf(rid) * sectorAngle - Math.PI / 2;\n  }\n\n  function agentAngle(aid) {\n    const p = parent(aid);\n    const base = p ? repoAngle(p) : 0;\n    const sibs = p ? childrenOfType(p, 'agent') : ofType('agent');\n    return spreadAngle(base, sibs, aid, ANGLE_FILL);\n  }\n\n  function agentNodeAngle(nid) {\n    const p = parent(nid);\n    if (!p) {\n      // Orphan agent_node: cluster near the average angle of parented ones\n      const all = ofType('agent_node');\n      let sum = 0, count = 0;\n      for (const an of all) {\n        const ap = parent(an);\n        if (ap) { sum += agentAngle(ap); count++; }\n      }\n      const base = count > 0 ? sum / count : 0;\n      const orphans = all.filter(n => !parent(n));\n      const oi = orphans.indexOf(nid);\n      const n = orphans.length;\n      return base + (n <= 1 ? 0 : (oi / (n - 1) - 0.5) * sectorAngle * ANGLE_FILL);\n    }\n    const sibs = childrenOfType(p, 'agent_node');\n    return spreadAngle(agentAngle(p), sibs, nid, ANGLE_FILL * 0.8);\n  }\n\n  // ── Repo ──────────────────────────────────────────────────────────────────\n  if (type === 'repo') {\n    return polar(repoAngle(id), R.repo);\n  }\n\n  // ── Agent ─────────────────────────────────────────────────────────────────\n  if (type === 'agent') {\n    return polar(agentAngle(id), R.agent);\n  }\n\n  // ── Agent node (Prometheus sub-nodes) ─────────────────────────────────────\n  if (type === 'agent_node') {\n    return polar(agentNodeAngle(id), R.agent_node);\n  }\n\n  // ── Prompt ────────────────────────────────────────────────────────────────\n  if (type === 'prompt') {\n    const p = parent(id);\n    if (!p) return polar(0, R.prompt_of_agent);\n\n    const pType = graph.getNodeAttribute(p, 'node_type');\n    const isUnderNode = pType === 'agent_node';\n    const base = isUnderNode ? agentNodeAngle(p) : agentAngle(p);\n    const sibs = childrenOfType(p, 'prompt');\n    const a = spreadAngle(base, sibs, id, ANGLE_FILL * 0.7);\n    const r = isUnderNode ? R.prompt_of_node : R.prompt_of_agent;\n    return polar(a, r);\n  }\n\n  // ── Tool ──────────────────────────────────────────────────────────────────\n  if (type === 'tool') {\n    const tools = ofType('tool');\n    const i = tools.indexOf(id);\n    // Distribute tools evenly around the full outermost ring\n    const a = (i / Math.max(tools.length, 1)) * TWO_PI - Math.PI / 2;\n    return polar(a, R.tool);\n  }\n\n  return { x: 0, y: 0 };\n}",
        "Function>>"
      ]
    }
  }
},
    hierarchical:  {
  "metrics": {},
  "layoutsParameters": {
    "script": {
      "script": [
        "<<Function",
        "function nodeCoordinates(id, attributes, index, graph) {\n  const type = attributes.node_type;\n\n  const scale = 1;\n\n  // ── Spacing constants ────────────────────────────────────────────────────\n  const COL_SPACING = 500*scale;  // horizontal distance between columns (decrease to compress)\n\n  // agent_node and regular prompts share column 2.\n  // Prometheus prompts (children of agent_node) go one column further.\n  const COLS = {\n    repo:              0,\n    agent:             COL_SPACING,\n    agent_node:        COL_SPACING * 2,   // Prometheus sub-nodes\n    prompt_of_agent:   COL_SPACING * 2,   // regular agents → share col with agent_node\n    prompt_of_node:    COL_SPACING * 3,   // Prometheus agent_node children\n    tool:              COL_SPACING * 4,\n  };\n\n  // Base row height; agents within a repo are spaced H apart.\n  // Repos themselves are spaced 3 × H apart so sibling agents don't overlap.\n  const H = 150*scale;\n\n  // ── Helpers ──────────────────────────────────────────────────────────────\n  const allNodes = graph.nodes();\n\n  function ofType(t) {\n    return allNodes.filter(n => graph.getNodeAttribute(n, 'node_type') === t);\n  }\n\n  function parent(nid) {\n    const ins = graph.inNeighbors(nid);\n    return ins.length > 0 ? ins[0] : null;\n  }\n\n  function childrenOfType(pid, t) {\n    return graph.outNeighbors(pid)\n      .filter(n => graph.getNodeAttribute(n, 'node_type') === t);\n  }\n\n  // Vertical centre of a sibling group around a focal y\n  function groupY(focalY, siblings, selfId, spacing) {\n    const i = siblings.indexOf(selfId);\n    const offset = (i - (siblings.length - 1) / 2) * spacing;\n    return focalY + offset;\n  }\n\n  // ── Repo ─────────────────────────────────────────────────────────────────\n  const repos = ofType('repo');\n\n  function repoY(rid) {\n    return repos.indexOf(rid) * H * 3;\n  }\n\n  if (type === 'repo') {\n    return { x: COLS.repo, y: repoY(id) };\n  }\n\n  // ── Agent ─────────────────────────────────────────────────────────────────\n  function agentY(aid) {\n    const p = parent(aid);\n    const ry = p ? repoY(p) : 0;\n    const sibs = p ? childrenOfType(p, 'agent') : ofType('agent');\n    return groupY(ry, sibs, aid, H);\n  }\n\n  if (type === 'agent') {\n    return { x: COLS.agent, y: agentY(id) };\n  }\n\n  // ── Agent node (Prometheus sub-nodes) ────────────────────────────────────\n  function agentNodeY(nid) {\n    const p = parent(nid);\n    if (!p) {\n      // Orphan: no parent agent. Anchor near the average y of agent_nodes that do\n      // have a parent, so they stay close to the Prometheus cluster.\n      const allAgentNodes = ofType('agent_node');\n      let anchorY = 0, count = 0;\n      for (const an of allAgentNodes) {\n        const ap = parent(an);\n        if (ap) { anchorY += agentY(ap); count++; }\n      }\n      if (count > 0) anchorY /= count;\n      const orphans = allAgentNodes.filter(n => !parent(n));\n      const oi = orphans.indexOf(nid);\n      return anchorY + (oi - (orphans.length - 1) / 2) * H * 0.75;\n    }\n    const sibs = childrenOfType(p, 'agent_node');\n    return groupY(agentY(p), sibs, nid, H * 0.75);\n  }\n\n  if (type === 'agent_node') {\n    return { x: COLS.agent_node, y: agentNodeY(id) };\n  }\n\n  // ── Prompt ───────────────────────────────────────────────────────────────\n  if (type === 'prompt') {\n    const p = parent(id);\n    if (!p) return { x: COLS.prompt_of_agent, y: index * H * 0.6 };\n\n    const pType = graph.getNodeAttribute(p, 'node_type');\n    const isUnderNode = pType === 'agent_node';\n    const py = isUnderNode ? agentNodeY(p) : agentY(p);\n    const x  = isUnderNode ? COLS.prompt_of_node : COLS.prompt_of_agent;\n    const sibs = childrenOfType(p, 'prompt');\n    return { x, y: groupY(py, sibs, id, H * 0.55) };\n  }\n\n  // ── Tool ─────────────────────────────────────────────────────────────────\n  if (type === 'tool') {\n    const tools = ofType('tool');\n    const i = tools.indexOf(id);\n    // Spread tools over the same vertical range as the repo column\n    const graphHeight = repos.length * H * 3;\n    const spacing = graphHeight / Math.max(tools.length, 1);\n    return { x: COLS.tool, y: i * spacing - graphHeight * 0.1 };\n  }\n\n  // Fallback\n  return { x: 0, y: index * H };\n}",
        "Function>>"
      ]
    }
  }
}
  };
  // Map of repo id -> GEXF filename (relative to this page).
  // Built from the contents of repo_graph/exports/.
  var REPO_GEXF = {"repo_SWE_agent":"repo_SWE_agent.gexf","repo_navie_editor":"repo_navie_editor.gexf","repo_agentscope":"repo_agentscope.gexf","repo_moatless_tools":"repo_moatless_tools.gexf","repo_Lingma_SWE_GPT":"repo_Lingma_SWE_GPT.gexf","repo_OpenHands":"repo_OpenHands.gexf","repo_debug_gym":"repo_debug_gym.gexf","repo_claude_coder":"repo_claude_coder.gexf","repo_MCTS_Refine_Codes":"repo_MCTS_Refine_Codes.gexf","repo_Lingxi":"repo_Lingxi.gexf","repo_Prometheus":"repo_Prometheus.gexf","repo_OrcaLoca":"repo_OrcaLoca.gexf","repo_programmer":"repo_programmer.gexf","repo_Agentless":"repo_Agentless.gexf","repo_SuperCoder":"repo_SuperCoder.gexf","repo_suna":"repo_suna.gexf","repo_mini_SWE_agent":"repo_mini_SWE_agent.gexf","repo_trae_agent":"repo_trae_agent.gexf","repo_RepoGraph":"repo_RepoGraph.gexf","repo_DARS_Agent":"repo_DARS_Agent.gexf","repo_patchwork":"repo_patchwork.gexf","repo_CodeSouler":"repo_CodeSouler.gexf","repo_KGCompass":"repo_KGCompass.gexf","repo_ExpeRepair":"repo_ExpeRepair.gexf","repo_engine_core":"repo_engine_core.gexf","repo_ridges":"repo_ridges.gexf","repo_CodeR":"repo_CodeR.gexf","repo_SWE_Fixer":"repo_SWE_Fixer.gexf","repo_SWE_Dev":"repo_SWE_Dev.gexf","repo_auto_code_rover":"repo_auto_code_rover.gexf","repo_HyperAgent":"repo_HyperAgent.gexf","repo_aegis":"repo_aegis.gexf","repo_Co_PatcheR":"repo_Co_PatcheR.gexf","repo_augment_swebench_agent":"repo_augment_swebench_agent.gexf","repo_swe_rl":"repo_swe_rl.gexf","repo_aware_swe_agent":"repo_aware_swe_agent.gexf","repo_live_swe_agent":"repo_live_swe_agent.gexf","repo_refact":"repo_refact.gexf","repo_Agentless_Lite":"repo_Agentless_Lite.gexf","repo_AnonymousSWEGPT":"repo_AnonymousSWEGPT.gexf","repo_joycode_agent":"repo_joycode_agent.gexf","repo_SWE_bench":"repo_SWE_bench.gexf","repo_aide":"repo_aide.gexf","repo_Skywork_SWE_32B":"repo_Skywork_SWE_32B.gexf","repo_CodeFuse_CGM":"repo_CodeFuse_CGM.gexf"};
  // Filename used when no ?repo= is given (the full graph).
  var DEFAULT_GEXF = "swe_bench_graph.gexf";

  // ── URL params ─────────────────────────────────────────────────────────────
  var params = new URLSearchParams(window.location.search);
  var repo   = params.get("repo");
  var layout = params.get("layout") || "radial";

  // ── Apply layout (1.0_session) ─────────────────────────────────────────────
  if (SESSIONS[layout]) {
    try {
      sessionStorage.setItem("1.0_session", JSON.stringify(SESSIONS[layout]));
    } catch (e) {
      console.warn("[repo-graph boot] failed to write 1.0_session:", e);
    }
  }

  // Make sure no stale filter from a previous visit interferes — the
  // pre-filtered GEXFs already represent the subset the user asked for.
  try { sessionStorage.removeItem("1.0_filters"); } catch (e) {}

  // ── Pick the GEXF file ─────────────────────────────────────────────────────
  // Normalise: accept both "repo_OpenHands" and "OpenHands".
  var gexfFile = DEFAULT_GEXF;
  if (repo) {
    var key = repo.indexOf("repo_") === 0 ? repo : "repo_" + repo;
    if (Object.prototype.hasOwnProperty.call(REPO_GEXF, key)) {
      gexfFile = REPO_GEXF[key];
    } else {
      console.warn("[repo-graph boot] unknown repo '" + repo + "', falling back to full graph");
    }
  }

  // ── Tell gephi-lite to auto-fetch the GEXF (?file=…) ──────────────────────
  if (!params.has("file")) {
    var gexfUrl = new URL("./" + gexfFile, window.location.href).href;
    params.set("file", gexfUrl);
    var newUrl = window.location.pathname + "?" + params.toString() + window.location.hash;
    // Replace the URL synchronously without reloading; gephi-lite's
    // Initialize.tsx reads window.location.href after this script returns.
    window.history.replaceState(null, "", newUrl);
  }
})();
