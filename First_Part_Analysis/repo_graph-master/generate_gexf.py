#!/usr/bin/env python3
"""
generate_gexf.py
Generate a GEXF graph for the SWE-bench repository analysis (Gephi Lite).

Node types
  repo       : one per repository row in the repositories CSV
  agent      : one per row in a repo's agent CSV (Table 1 in multi-section CSVs)
  agent_node : implementation-level node inside an agent (Table 2 in Prometheus-style CSVs)
  prompt     : one per prompt group in an agent / agent_node row
  tool       : one per unique tool URL (globally deduplicated)

Edges (directed)
  repo       -> agent       (has_agent)
  agent      -> agent_node  (has_node)   ← Prometheus-style only
  agent_node -> prompt      (has_prompt) ← Prometheus-style only
  agent_node -> tool        (has_tool)   ← Prometheus-style only
  agent      -> prompt      (has_prompt)
  agent      -> tool        (has_tool)
"""

import csv
import io
import json
import re
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE           = Path(r"C:\Users\XF\Desktop\TFG_public\First_Part_Analysis")
REPO_CSV       = BASE / "Open-Source-Proyects-SWE-Bench - Repositories.csv"
AGENT_TYPE_CSV = BASE / "Open-Source-Proyects-SWE-Bench - AgentType.csv"
AGENTS_DIR     = BASE / "Prompt_Analysis" / "agents_csv"
OUTPUT         = Path(__file__).parent / "raw_swe_bench_graph.gexf"
DATASET_OUTPUT = Path(__file__).parent / "config" / "dataset.json"

# ---------------------------------------------------------------------------
# Unified GEXF attribute schema  (all "string" for robustness)
# ---------------------------------------------------------------------------
ATTRS = [
    ("0",  "node_type"),
    # repo
    ("1",  "url"),
    ("2",  "commits"),
    ("3",  "releases"),
    ("4",  "stars"),
    ("5",  "analyzed"),
    ("6",  "publication"),
    ("7",  "framework"),
    ("8",  "dependency_graph"),
    ("9",  "has_agents"),
    ("10", "num_agents"),
    ("11", "topology_description"),
    ("12", "topology_file"),
    ("13", "topology_type"),
    ("14", "topology_url"),
    ("15", "programming_language"),
    ("16", "autonomy_rating"),
    ("17", "autonomy_description"),
    ("18", "repo_comments"),
    # agent / agent_node  (same attributes, node_type distinguishes them)
    ("19", "agent_name"),
    ("20", "agent_type"),
    ("21", "short_description"),
    ("22", "agent_in_repo"),
    ("23", "agent_comment"),
    # prompt
    ("24", "prompt_type"),
    ("25", "prompt_text"),
    ("26", "prompt_url"),
    # tool
    ("27", "tool_url"),
]
ATTR_ID = {title: aid for aid, title in ATTRS}

REPO_COL_MAP = {
    "url":                  "url",
    "commits":              "commits",
    "releases":             "releases",
    "stars":                "stars",
    "Analyzed?":            "analyzed",
    "Publication? (the Readme.md of the repo usually includes the link or name of the publication)": "publication",
    "Framework used (e.g. langchain, langgraph, use their own scripts, the project is a framework itself -Moatless, Openhand-)": "framework",
    "Dependency graph":     "dependency_graph",
    "Has Agents?":          "has_agents",
    "# Agents":             "num_agents",
    "Topology/Architecture Description": "topology_description",
    "Topology/Architecture File":        "topology_file",
    "Topology/Architecture Type":        "topology_type",
    "Topology URL":         "topology_url",
    "Programming language": "programming_language",
    "Autonomy Rating":      "autonomy_rating",
    "Autonomy Description": "autonomy_description",
    "Comments":             "repo_comments",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def nv(v):
    if v is None:
        return "null"
    v = str(v).strip()
    return v if v else "null"

def safe_id(s):
    return re.sub(r"[^\w]", "_", str(s))

def url_tail(url):
    parts = [p for p in url.rstrip("/").split("/") if p]
    return parts[-1][:60] if parts else url[:60]

def url_hash(url):
    return hashlib.md5(url.encode()).hexdigest()[:10]

def normalize(s):
    return re.sub(r"[-_ ]", "", s.lower())

def build_csv_map():
    return {normalize(p.stem): p for p in AGENTS_DIR.glob("*.csv")}

def build_agent_type_map():
    """
    Parse AgentType.csv into {normalized_repo: {normalized_agent_name: type_label}}.
    Header row gives type labels; first column is the repo; remaining cells contain
    comma/newline-separated agent names (with optional "(Parent)" suffix).
    """
    out = {}
    if not AGENT_TYPE_CSV.exists():
        return out
    with open(AGENT_TYPE_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return out
    header = rows[0]
    type_labels = header[1:]
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        repo_key = normalize(row[0])
        if repo_key in ("description",):
            continue
        repo_entry = out.setdefault(repo_key, {})
        for idx, cell in enumerate(row[1:]):
            if idx >= len(type_labels):
                break
            label = type_labels[idx].strip()
            if not label or not cell or not cell.strip():
                continue
            for raw in re.split(r"[,\n]", cell):
                name = raw.strip()
                if not name:
                    continue
                name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
                if name:
                    repo_entry.setdefault(normalize(name), label)
    return out

# ---------------------------------------------------------------------------
# Dataset skeleton  (Gephi Lite 1.0_dataset format)
# ---------------------------------------------------------------------------

def build_dataset():
    node_fields = [{"id": "label", "itemType": "node", "quantitative": False}]
    for _, title in ATTRS:
        node_fields.append({"id": title, "itemType": "node", "quantitative": False})

    edge_fields = [{"id": "label", "itemType": "edge", "quantitative": False}]

    return {
        "nodeData":  {},
        "edgeData":  {},
        "layout":    {},
        "metadata":  {"title": "SWE-bench Graph"},
        "nodeFields": node_fields,
        "edgeFields": edge_fields,
        "fullGraph": {"nodes": [], "edges": []},
    }

# ---------------------------------------------------------------------------
# Column detection  (handles both "Prompt N" and "Prompts N" spellings)
# ---------------------------------------------------------------------------

def detect_cols(headers):
    """
    Returns:
      prompt_groups : {N: {'type': col, 'text': col, 'url': col}}  (keys optional)
      tool_cols     : [col, ...]
      comment_col   : col name or None
    """
    prompt_groups = {}
    tool_cols = []
    comment_col = None
    for h in headers:
        if re.fullmatch(r"Prompts?\s+(\d+)\s+Type", h, re.I):
            n = int(re.search(r"\d+", h).group())
            prompt_groups.setdefault(n, {})["type"] = h
        elif re.fullmatch(r"URL\s+Prompts?\s+(\d+)", h, re.I):
            n = int(re.search(r"\d+", h).group())
            prompt_groups.setdefault(n, {})["url"] = h
        elif re.fullmatch(r"Prompts?\s+(\d+)", h, re.I):
            n = int(re.search(r"\d+", h).group())
            prompt_groups.setdefault(n, {})["text"] = h
        elif re.fullmatch(r"URL\s+Tool\s+\d+", h, re.I):
            tool_cols.append(h)
        elif h.strip().lower() in ("comment", "comments"):
            comment_col = h
    return prompt_groups, tool_cols, comment_col

# ---------------------------------------------------------------------------
# Multi-section CSV splitting  (Prometheus-style files)
# ---------------------------------------------------------------------------

def split_csv_sections(path):
    """
    Return list of raw-text strings, one per CSV section.
    A new section begins whenever a line has '#' as its first CSV field
    and at least 3 columns (distinguishes a header row from empty rows).
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        lines = f.readlines()

    header_indices = []
    for i, line in enumerate(lines):
        row = next(csv.reader([line]))
        if row and row[0].strip() == "#" and len(row) >= 3:
            header_indices.append(i)

    if len(header_indices) <= 1:
        return None   # single-section file

    sections = []
    for j, start in enumerate(header_indices):
        end = header_indices[j + 1] if j + 1 < len(header_indices) else len(lines)
        sections.append("".join(lines[start:end]))
    return sections

# ---------------------------------------------------------------------------
# GEXF node / edge writers
# ---------------------------------------------------------------------------

def add_node(nodes_el, node_id, label, attvalues, dataset=None):
    node = ET.SubElement(nodes_el, "node", id=node_id, label=label[:120])
    avs = ET.SubElement(node, "attvalues")
    for attr_name, raw_value in attvalues.items():
        ET.SubElement(avs, "attvalue",
                      **{"for": ATTR_ID[attr_name], "value": nv(raw_value)})
    if dataset is not None:
        entry = {"label": label[:120]}
        entry.update({k: nv(v) for k, v in attvalues.items()})
        dataset["nodeData"][node_id] = entry
        dataset["layout"][node_id] = {"x": 0.0, "y": 0.0}
        dataset["fullGraph"]["nodes"].append({"key": node_id, "attributes": dict(entry)})

def add_edge(edges_el, eid, src, tgt, label, dataset=None):
    ET.SubElement(edges_el, "edge",
                  id=str(eid), source=src, target=tgt, label=label)
    if dataset is not None:
        edge_id = str(eid)
        dataset["edgeData"][edge_id] = {"label": label}
        dataset["fullGraph"]["edges"].append({
            "key": edge_id, "source": src, "target": tgt,
            "attributes": {"label": label},
        })

# ---------------------------------------------------------------------------
# Prompt + tool emission (shared by single-section and multi-section paths)
# ---------------------------------------------------------------------------

def emit_prompts_tools(row, parent_id, id_prefix,
                       prompt_groups, tool_cols, comment_col,
                       nodes_el, edges_el, tool_map, counters, dataset=None):
    for n in sorted(prompt_groups):
        pg = prompt_groups[n]
        ptype = nv(row.get(pg.get("type", ""), ""))
        ptext = nv(row.get(pg.get("text", ""), ""))
        purl  = nv(row.get(pg.get("url",  ""), ""))
        if ptype == "null" and ptext == "null" and purl == "null":
            continue
        prompt_id = f"prompt_{id_prefix}_{n}"
        label_body = ptext if ptext != "null" else purl
        label = (f"{ptype}: {label_body.split("=")[0][:40]}"
                 if ptype != "null" else label_body[:40])
        add_node(nodes_el, prompt_id, label, {
            "node_type":   "prompt",
            "prompt_type": ptype,
            "prompt_text": ptext,
            "prompt_url":  purl,
        }, dataset)
        counters["prompts"] += 1
        add_edge(edges_el, counters["edges"], parent_id, prompt_id, "has_prompt", dataset)
        counters["edges"] += 1

    for tcol in tool_cols:
        turl = nv(row.get(tcol, ""))
        if turl == "null":
            continue
        if turl not in tool_map:
            tid = "tool_" + url_hash(turl)
            add_node(nodes_el, tid, url_tail(turl), {
                "node_type": "tool",
                "tool_url":  turl,
            }, dataset)
            tool_map[turl] = tid
            counters["tools"] += 1
        add_edge(edges_el, counters["edges"], parent_id, tool_map[turl], "has_tool", dataset)
        counters["edges"] += 1

# ---------------------------------------------------------------------------
# Standard single-section CSV  (most repos)
# ---------------------------------------------------------------------------

def resolve_agent_type(agent_name, csv_value, repo_name, agent_type_map):
    repo_types = agent_type_map.get(normalize(repo_name)) if agent_type_map else None
    if repo_types:
        looked_up = repo_types.get(normalize(agent_name))
        if looked_up:
            return looked_up
    return csv_value

def process_agent_csv(path, repo_name, repo_node_id,
                      nodes_el, edges_el, tool_map, counters,
                      dataset=None, agent_type_map=None):
    sections = split_csv_sections(path)
    if sections is not None:
        process_multisection_csv(sections, repo_name, repo_node_id,
                                 nodes_el, edges_el, tool_map, counters,
                                 dataset, agent_type_map)
        return

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        prompt_groups, tool_cols, comment_col = detect_cols(headers)

        row_idx = 0
        for row in reader:
            a_name = nv(row.get("Name", ""))
            if a_name in ("null", "Name", "Short Description"):
                continue
            agent_id = f"agent_{safe_id(repo_name)}_{row_idx}"
            row_idx += 1

            add_node(nodes_el, agent_id, a_name, {
                "node_type":         "agent",
                "agent_name":        a_name,
                "agent_type":        resolve_agent_type(
                                         a_name, row.get("Agent Type", ""),
                                         repo_name, agent_type_map),
                "short_description": row.get("Short Description", ""),
                "agent_in_repo":     row.get("Agent in the repo", ""),
                "agent_comment":     row.get(comment_col, "") if comment_col else "",
            }, dataset)
            counters["agents"] += 1
            add_edge(edges_el, counters["edges"], repo_node_id, agent_id, "has_agent", dataset)
            counters["edges"] += 1

            emit_prompts_tools(row, agent_id,
                               f"{safe_id(repo_name)}_{row_idx - 1}",
                               prompt_groups, tool_cols, comment_col,
                               nodes_el, edges_el, tool_map, counters, dataset)

# ---------------------------------------------------------------------------
# Multi-section CSV  (Prometheus-style: Table 1 = agents, Table 2 = nodes)
# ---------------------------------------------------------------------------

def process_multisection_csv(sections, repo_name, repo_node_id,
                              nodes_el, edges_el, tool_map, counters,
                              dataset=None, agent_type_map=None):
    section1_text = sections[0]
    section2_text = sections[1] if len(sections) > 1 else ""

    # ── Step 1: parse Table 2 (implementation nodes with prompts / tools) ──
    node_id_map = {}   # node_name -> node_id

    if section2_text:
        node_reader = csv.DictReader(io.StringIO(section2_text))
        n_headers = node_reader.fieldnames or []
        n_pg, n_tc, n_cc = detect_cols(n_headers)

        node_row_idx = 0
        for row in node_reader:
            n_name = nv(row.get("Name", ""))
            if n_name in ("null", "Name"):
                continue
            node_id = f"node_{safe_id(repo_name)}_{node_row_idx}"
            node_id_map[n_name] = node_id
            node_row_idx += 1

            add_node(nodes_el, node_id, n_name, {
                "node_type":         "agent_node",
                "agent_name":        n_name,
                "agent_type":        "null",
                "short_description": row.get("Short Description", ""),
                "agent_in_repo":     row.get("Agent in the repo", ""),
                "agent_comment":     row.get(n_cc, "") if n_cc else "",
            }, dataset)
            counters["agent_nodes"] += 1

            emit_prompts_tools(row, node_id,
                               f"{safe_id(repo_name)}_node{node_row_idx - 1}",
                               n_pg, n_tc, n_cc,
                               nodes_el, edges_el, tool_map, counters, dataset)

    # ── Step 2: parse Table 1 (high-level agents) ──────────────────────────
    agent_reader = csv.DictReader(io.StringIO(section1_text))

    row_idx = 0
    for row in agent_reader:
        a_name = nv(row.get("Name", ""))
        if a_name in ("null", "Name", "Short Description"):
            continue
        agent_id = f"agent_{safe_id(repo_name)}_{row_idx}"
        row_idx += 1

        add_node(nodes_el, agent_id, a_name, {
            "node_type":         "agent",
            "agent_name":        a_name,
            "agent_type":        resolve_agent_type(
                                     a_name, row.get("Agent Type", ""),
                                     repo_name, agent_type_map),
            "short_description": row.get("Short Description", ""),
            "agent_in_repo":     row.get("Agent in the repo", ""),
            "agent_comment":     row.get("Comments", ""),
        }, dataset)
        counters["agents"] += 1
        add_edge(edges_el, counters["edges"], repo_node_id, agent_id, "has_agent", dataset)
        counters["edges"] += 1

        # Connect agent -> its implementation nodes via the "Nodes" column
        nodes_col = row.get("Nodes", "").strip()
        for n_name in [n.strip() for n in nodes_col.split(",") if n.strip()]:
            if n_name in node_id_map:
                add_edge(edges_el, counters["edges"],
                         agent_id, node_id_map[n_name], "has_node", dataset)
                counters["edges"] += 1

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    csv_map        = build_csv_map()
    agent_type_map = build_agent_type_map()
    consumed = set()
    tool_map = {}
    dataset  = build_dataset()
    counters = {"agents": 0, "agent_nodes": 0, "prompts": 0,
                "tools": 0, "edges": 0}

    gexf  = ET.Element("gexf", xmlns="http://gexf.net/1.3", version="1.3")
    graph = ET.SubElement(gexf, "graph",
                          defaultedgetype="directed", mode="static")

    attrs_el = ET.SubElement(graph, "attributes",
                              **{"class": "node", "mode": "static"})
    for aid, title in ATTRS:
        ET.SubElement(attrs_el, "attribute", id=aid, title=title, type="string")

    nodes_el = ET.SubElement(graph, "nodes")
    edges_el = ET.SubElement(graph, "edges")
    n_repos  = 0

    # ── repos from repositories CSV ──────────────────────────────────────────
    with open(REPO_CSV, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            repo_name = nv(row.get("repo", ""))
            if repo_name == "null":
                continue
            repo_id = "repo_" + safe_id(repo_name)

            repo_attrs = {"node_type": "repo"}
            for csv_col, attr in REPO_COL_MAP.items():
                repo_attrs[attr] = row.get(csv_col, "")
            add_node(nodes_el, repo_id, repo_name, repo_attrs, dataset)
            n_repos += 1

            key = normalize(repo_name)
            if key in csv_map and key not in consumed:
                consumed.add(key)
                process_agent_csv(csv_map[key], repo_name, repo_id,
                                  nodes_el, edges_el, tool_map, counters,
                                  dataset, agent_type_map)

    # ── orphan agent CSVs (not matched to any repo row) ─────────────────────
    NULL_ATTRS = {attr: "null" for _, attr in ATTRS if attr != "node_type"}
    for key, path in csv_map.items():
        if key in consumed:
            continue
        repo_name = path.stem
        repo_id   = "repo_" + safe_id(repo_name)
        orphan_attrs = {"node_type": "repo"}
        orphan_attrs.update(NULL_ATTRS)
        add_node(nodes_el, repo_id, repo_name, orphan_attrs, dataset)
        n_repos += 1
        process_agent_csv(path, repo_name, repo_id,
                          nodes_el, edges_el, tool_map, counters,
                          dataset, agent_type_map)

    # ── write GEXF ────────────────────────────────────────────────────────────
    tree = ET.ElementTree(gexf)
    try:
        ET.indent(tree, space="  ")     # Python >= 3.9
    except AttributeError:
        pass
    tree.write(str(OUTPUT), encoding="utf-8", xml_declaration=True)

    # ── write dataset.json (Gephi Lite 1.0_dataset format) ───────────────────
    DATASET_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(DATASET_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    total_nodes = (n_repos + counters["agents"] + counters["agent_nodes"]
                   + counters["prompts"] + counters["tools"])
    print(f"Repos        : {n_repos}")
    print(f"Agents       : {counters['agents']}")
    print(f"Agent nodes  : {counters['agent_nodes']}  (Prometheus-style sub-nodes)")
    print(f"Prompts      : {counters['prompts']}")
    print(f"Tools        : {counters['tools']}  (unique URLs)")
    print(f"Total nodes  : {total_nodes}")
    print(f"Edges        : {counters['edges']}")
    print(f"Written      : {OUTPUT}")
    print(f"Dataset      : {DATASET_OUTPUT}")

if __name__ == "__main__":
    main()
