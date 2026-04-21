/**
 * Custom Gephi Lite layout: radial / sunburst by node_type
 *
 * Rings (centre → outside):
 *   repo  →  agent  →  agent_node / prompt  →  prompt (Prometheus)  →  tool
 *
 * Each repo occupies an angular sector. Children fan out within that sector.
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

  // ── Spacing constants ─────────────────────────────────────────────────────
  const RING = 300;         // distance between rings (increase to spread out)
  const ANGLE_FILL = 0.7;   // fraction of a sector used by siblings (0–1, increase to spread wider)

  const R = {
    repo:            RING * 1,
    agent:           RING * 2,
    agent_node:      RING * 3,  // Prometheus sub-nodes
    prompt_of_agent: RING * 3,  // regular prompts share ring with agent_node
    prompt_of_node:  RING * 4,  // Prometheus prompts one ring further out
    tool:            RING * 5,
  };

  // ── Helpers ───────────────────────────────────────────────────────────────
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

  function polar(angle, radius) {
    return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
  }

  // Spread siblings evenly within a fraction of the sector angle.
  // Returns the angle for selfId among its siblings.
  function spreadAngle(baseAngle, siblings, selfId, fraction) {
    const n = siblings.length;
    if (n <= 1) return baseAngle;
    const i = siblings.indexOf(selfId);
    const arc = sectorAngle * fraction;
    return baseAngle + (i / (n - 1) - 0.5) * arc;
  }

  // ── Sector geometry ───────────────────────────────────────────────────────
  const repos = ofType('repo');
  const TWO_PI = 2 * Math.PI;
  const sectorAngle = TWO_PI / Math.max(repos.length, 1);

  // Start at the top (-π/2) and go clockwise
  function repoAngle(rid) {
    return repos.indexOf(rid) * sectorAngle - Math.PI / 2;
  }

  function agentAngle(aid) {
    const p = parent(aid);
    const base = p ? repoAngle(p) : 0;
    const sibs = p ? childrenOfType(p, 'agent') : ofType('agent');
    return spreadAngle(base, sibs, aid, ANGLE_FILL);
  }

  function agentNodeAngle(nid) {
    const p = parent(nid);
    if (!p) {
      // Orphan agent_node: cluster near the average angle of parented ones
      const all = ofType('agent_node');
      let sum = 0, count = 0;
      for (const an of all) {
        const ap = parent(an);
        if (ap) { sum += agentAngle(ap); count++; }
      }
      const base = count > 0 ? sum / count : 0;
      const orphans = all.filter(n => !parent(n));
      const oi = orphans.indexOf(nid);
      const n = orphans.length;
      return base + (n <= 1 ? 0 : (oi / (n - 1) - 0.5) * sectorAngle * ANGLE_FILL);
    }
    const sibs = childrenOfType(p, 'agent_node');
    return spreadAngle(agentAngle(p), sibs, nid, ANGLE_FILL * 0.8);
  }

  // ── Repo ──────────────────────────────────────────────────────────────────
  if (type === 'repo') {
    return polar(repoAngle(id), R.repo);
  }

  // ── Agent ─────────────────────────────────────────────────────────────────
  if (type === 'agent') {
    return polar(agentAngle(id), R.agent);
  }

  // ── Agent node (Prometheus sub-nodes) ─────────────────────────────────────
  if (type === 'agent_node') {
    return polar(agentNodeAngle(id), R.agent_node);
  }

  // ── Prompt ────────────────────────────────────────────────────────────────
  if (type === 'prompt') {
    const p = parent(id);
    if (!p) return polar(0, R.prompt_of_agent);

    const pType = graph.getNodeAttribute(p, 'node_type');
    const isUnderNode = pType === 'agent_node';
    const base = isUnderNode ? agentNodeAngle(p) : agentAngle(p);
    const sibs = childrenOfType(p, 'prompt');
    const a = spreadAngle(base, sibs, id, ANGLE_FILL * 0.7);
    const r = isUnderNode ? R.prompt_of_node : R.prompt_of_agent;
    return polar(a, r);
  }

  // ── Tool ──────────────────────────────────────────────────────────────────
  if (type === 'tool') {
    const tools = ofType('tool');
    const i = tools.indexOf(id);
    // Distribute tools evenly around the full outermost ring
    const a = (i / Math.max(tools.length, 1)) * TWO_PI - Math.PI / 2;
    return polar(a, R.tool);
  }

  return { x: 0, y: 0 };
}
