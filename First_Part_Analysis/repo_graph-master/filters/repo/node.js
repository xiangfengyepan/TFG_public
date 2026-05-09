/**
 * Filtering function.
 *
 * @param {string} id ID of the item
 * @param {Object.<string, number | string | boolean | undefined | null>} attributes Attributes of the item
 * @param {FullGraph} full graph (data and rendering attributes + topology) dataset
 * @return {boolean} TRUE if the item should be kept in the graph, FALSE to filter it
 */

function nodeFilter(id, attributes, graph) {
  const REPO_NODE = "repo_MCTS_Refine_Codes";

  // BFS from REPO_NODE; keep only nodes reachable via directed edges.
  // Cache the reachable set on the function object so BFS runs only once per filter application.
  if (!nodeFilter._reachable) {
    const reachable = new Set();
    const queue = [];
    if (graph.hasNode(REPO_NODE)) {
      reachable.add(REPO_NODE);
      queue.push(REPO_NODE);
    }
    while (queue.length > 0) {
      const cur = queue.shift();
      graph.outNeighbors(cur).forEach(function (nb) {
        if (!reachable.has(nb)) {
          reachable.add(nb);
          queue.push(nb);
        }
      });
    }
    nodeFilter._reachable = reachable;
  }
  return nodeFilter._reachable.has(id);
}
