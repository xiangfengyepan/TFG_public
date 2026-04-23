from paths import WORKFLOW_JSON, AGENT_CONFIG_DIR, DEFAULT_AGENT_CONFIG
from app.src.core.workflow import build_workflow

import json
from pathlib import Path


def export_workflow_to_json(workflow_file=WORKFLOW_JSON, config_dir=AGENT_CONFIG_DIR):
    # 1. Compile the graph to inspect structure
    app = build_workflow()
    graph = app.get_graph()

    nodes_data = []
    edges_data = []

    # helper to track positions
    node_map = {}

    # 2. Extract Nodes
    # We skip internal LangGraph start/end nodes for a cleaner UI
    visible_nodes = [
        n_id for n_id in graph.nodes if n_id not in ["__start__", "__end__"]
    ]

    for i, node_id in enumerate(visible_nodes):
        # Create a simple layout: Horizontal spacing of 200px
        x, y = i * 200, 100

        node_info = {
            "id": node_id,
            "x": x,
            "y": y,
            "name": node_id.capitalize(),
            "role": "Agent Node" if "node" not in node_id else "Processor",
            "details": f"Handles the {node_id} logic.",
        }
        nodes_data.append(node_info)
        node_map[node_id] = node_info

    # 3. Extract Edges
    for edge in graph.edges:
        # Only map edges between our visible nodes
        if edge.source in node_map and edge.target in node_map:
            edges_data.append({"source": edge.source, "target": edge.target})

    # 4. Save as a structured object
    full_workflow = {"nodes": nodes_data, "edges": edges_data}

    with open(workflow_file, "w") as f:
        json.dump(full_workflow, f, indent=2)

    data = {}
    with open(DEFAULT_AGENT_CONFIG, "r") as src:
        data = json.load(src)
        
    for node in full_workflow.get("nodes", []):
        node_id = node.get("id")

        output_path = Path(config_dir) / f"{node_id}.json"
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)

    print(
        f"Exported {len(nodes_data)} nodes and {len(edges_data)} edges to {workflow_file}"
    )


if __name__ == "__main__":
    export_workflow_to_json()
