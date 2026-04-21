/**
 * Filtering function.
 *
 * @param {string} id ID of the item
 * @param {Object.<string, number | string | boolean | undefined | null>} attributes Attributes of the item
 * @param {FullGraph} full graph (data and rendering attributes + topology) dataset
 * @return {boolean} TRUE if the item should be kept in the graph, FALSE to filter it
 */
function edgeFilter(id, attributes, graph) {
  // Edges whose endpoints are hidden by the node filter are automatically removed
  // by Gephi Lite; keep all edges here.
  return true;
}
