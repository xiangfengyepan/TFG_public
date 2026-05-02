/**
 * Custom Gephi Lite layout: hierarchical tree by node_type
 *
 * Columns (left to right):
 *   repo  →  agent  ──────────────→  prompt  |  tool
 *                  ↘  agent_node  →  prompt  |
 *
 * Vertical positions are derived from the parent-child structure so that
 * children cluster around their parent's y coordinate.
 *
 * node_type values: "repo", "agent", "agent_node", "prompt", "tool"
 *
 * @param {string} id
 * @param {Object} attributes
 * @param {number} index
 * @param {Graph} graph  (graphology instance)
 * @returns {{ x: number, y: number }}
 */
function nodeCoordinates(id, attributes, index, graph) {
  const type = attributes.node_type;

  const scale = 1;

  // ── Spacing constants ────────────────────────────────────────────────────
  const COL_SPACING = 500*scale;  // horizontal distance between columns (decrease to compress)

  // agent_node and regular prompts share column 2.
  // Prometheus prompts (children of agent_node) go one column further.
  const COLS = {
    repo:              0,
    agent:             COL_SPACING,
    agent_node:        COL_SPACING * 2,   // Prometheus sub-nodes
    prompt_of_agent:   COL_SPACING * 2,   // regular agents → share col with agent_node
    prompt_of_node:    COL_SPACING * 3,   // Prometheus agent_node children
    tool:              COL_SPACING * 4,
  };

  // Base row height; agents within a repo are spaced H apart.
  // Repos themselves are spaced 3 × H apart so sibling agents don't overlap.
  const H = 150*scale;

  // ── Helpers ──────────────────────────────────────────────────────────────
  const allNodes = graph.nodes();

  function ofType(t) {
    return allNodes.filter(n => graph.getNodeAttribute(n, 'node_type') === t);
  }

  function parent(nid) {
    const ins = graph.inNeighbors(nid);
    return ins.length > 0 ? ins[0] : null;
  }

  function childrenOfType(pid, t) {
    return graph.outNeighbors(pid)
      .filter(n => graph.getNodeAttribute(n, 'node_type') === t);
  }

  // Vertical centre of a sibling group around a focal y
  function groupY(focalY, siblings, selfId, spacing) {
    const i = siblings.indexOf(selfId);
    const offset = (i - (siblings.length - 1) / 2) * spacing;
    return focalY + offset;
  }

  // ── Repo ─────────────────────────────────────────────────────────────────
  const repos = ofType('repo');

  function repoY(rid) {
    return repos.indexOf(rid) * H * 3;
  }

  if (type === 'repo') {
    return { x: COLS.repo, y: repoY(id) };
  }

  // ── Agent ─────────────────────────────────────────────────────────────────
  function agentY(aid) {
    const p = parent(aid);
    const ry = p ? repoY(p) : 0;
    const sibs = p ? childrenOfType(p, 'agent') : ofType('agent');
    return groupY(ry, sibs, aid, H);
  }

  if (type === 'agent') {
    return { x: COLS.agent, y: agentY(id) };
  }

  // ── Agent node (Prometheus sub-nodes) ────────────────────────────────────
  function agentNodeY(nid) {
    const p = parent(nid);
    if (!p) {
      // Orphan: no parent agent. Anchor near the average y of agent_nodes that do
      // have a parent, so they stay close to the Prometheus cluster.
      const allAgentNodes = ofType('agent_node');
      let anchorY = 0, count = 0;
      for (const an of allAgentNodes) {
        const ap = parent(an);
        if (ap) { anchorY += agentY(ap); count++; }
      }
      if (count > 0) anchorY /= count;
      const orphans = allAgentNodes.filter(n => !parent(n));
      const oi = orphans.indexOf(nid);
      return anchorY + (oi - (orphans.length - 1) / 2) * H * 0.75;
    }
    const sibs = childrenOfType(p, 'agent_node');
    return groupY(agentY(p), sibs, nid, H * 0.75);
  }

  if (type === 'agent_node') {
    return { x: COLS.agent_node, y: agentNodeY(id) };
  }

  // ── Prompt ───────────────────────────────────────────────────────────────
  if (type === 'prompt') {
    const p = parent(id);
    if (!p) return { x: COLS.prompt_of_agent, y: index * H * 0.6 };

    const pType = graph.getNodeAttribute(p, 'node_type');
    const isUnderNode = pType === 'agent_node';
    const py = isUnderNode ? agentNodeY(p) : agentY(p);
    const x  = isUnderNode ? COLS.prompt_of_node : COLS.prompt_of_agent;
    const sibs = childrenOfType(p, 'prompt');
    return { x, y: groupY(py, sibs, id, H * 0.55) };
  }

  // ── Tool ─────────────────────────────────────────────────────────────────
  if (type === 'tool') {
    const tools = ofType('tool');
    const i = tools.indexOf(id);
    // Spread tools over the same vertical range as the repo column
    const graphHeight = repos.length * H * 3;
    const spacing = graphHeight / Math.max(tools.length, 1);
    return { x: COLS.tool, y: i * spacing - graphHeight * 0.1 };
  }

  // Fallback
  return { x: 0, y: index * H };
}
