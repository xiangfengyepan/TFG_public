from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.src.agents.base_agent import BaseAgent
from paths import REPO_SCANNER_AGENT_JSON


class RepoScannerAgent(BaseAgent):
    """
    Scans the repository and generates a lightweight directory tree JSON.

    Output:
    - Saves `repo_tree.json` at repo root
    - Returns `{"repo_tree": <tree>}`
    """

    # Directories to exclude from scanning
    EXCLUDED_DIRS: Set[str] = {
        "venv",
        "venv_win",
        "venv_wsl",
        ".venv",
        "env",
        "node_modules",
        ".git",
        "__pycache__",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
    }

    # File extensions to exclude
    EXCLUDED_EXTS: Set[str] = {
        ".pyc",
        ".pyo",
        ".log",
        ".lock",
    }

    # Explicitly include file extensions as "relevant" source files.
    # (Requirement: keep tree clean/lightweight for analysis.)
    INCLUDED_EXTS: Set[str] = {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".java",
        ".cpp",
        ".c",
        ".h",
        ".hpp",
        ".cs",
        ".go",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".kts",
        ".scala",
        ".sql",
        ".md",
        ".yml",
        ".yaml",
        ".toml",
        ".json",
        ".xml",
        ".txt",
        ".css",
        ".html",
        ".sh",
        ".ps1",
    }

    # TODO update
    def __init__(self, *, max_depth: int = 5, max_file_bytes: int = 1_000_000) -> None:
        super().__init__()
        self.max_depth = max_depth
        self.max_file_bytes = max_file_bytes
        with open(REPO_SCANNER_AGENT_JSON, "r") as f:
            self.hyperparameters = json.load(f)

    @staticmethod
    def _is_hidden_path_part(part: str) -> bool:
        return part.startswith(".")

    def _should_include_file(self, file_path: Path) -> bool:
        if any(self._is_hidden_path_part(p.name) for p in file_path.parents):
            # Covers hidden folders anywhere in the path.
            return False
        if file_path.name.startswith("."):
            return False

        if file_path.name == ".DS_Store":
            return False

        if file_path.suffix in self.EXCLUDED_EXTS:
            return False

        return file_path.suffix in self.INCLUDED_EXTS

    def _walk_paths(self, root: Path) -> Tuple[List[Path], List[Path]]:
        """
        Uses os.walk to collect directory and file paths, applying constraints.
        """
        included_files: List[Path] = []
        included_dirs: Set[Path] = set()
        root = root.resolve()

        # Normalize for depth counting
        root_str = str(root)
        for dirpath, dirnames, filenames in os.walk(root_str, topdown=True):
            current_dir = Path(dirpath)
            rel_dir = current_dir.relative_to(root)

            # Depth: root=0, children=1, ...
            depth = 0 if rel_dir.parts == () else len(rel_dir.parts)
            if depth > self.max_depth:
                dirnames[:] = []
                continue

            # Prune excluded/hidden directories in-place (os.walk topdown mode)
            pruned = []
            for d in dirnames:
                if d in self.EXCLUDED_DIRS:
                    continue
                if self._is_hidden_path_part(d):
                    continue
                pruned.append(d)
            dirnames[:] = pruned

            if depth <= self.max_depth:
                included_dirs.add(current_dir)

            for fname in filenames:
                file_path = current_dir / fname
                if self._is_hidden_path_part(fname):
                    continue
                if file_path.is_symlink():
                    continue
                if file_path.stat().st_size > self.max_file_bytes:
                    continue
                if self._should_include_file(file_path):
                    included_files.append(file_path)

        return list(included_dirs), included_files

    @classmethod
    def _insert_into_tree(
        cls, tree: Dict[str, Any], rel_path_parts: List[str], *, is_file: bool
    ) -> None:
        """
        Insert a file or directory into the JSON tree.
        """
        node = tree
        for i, part in enumerate(rel_path_parts):
            is_last = i == len(rel_path_parts) - 1
            children = node.setdefault("children", [])

            # Find existing child node
            child = None
            for c in children:
                if c.get("name") == part:
                    child = c
                    break
            if child is None:
                child = {
                    "name": part,
                    "type": "file" if (is_last and is_file) else "directory",
                }
                children.append(child)

            node = child

            if is_last and is_file:
                node["type"] = "file"

    # TODO use this method for efficiency
    @classmethod
    def _tree_from_files(
        cls, root_name: str, file_paths: List[Path], root_dir: Path
    ) -> Dict[str, Any]:
        tree: Dict[str, Any] = {"name": root_name, "type": "directory", "children": []}

        # Insert files (directories are inferred by insertion path)
        for f in file_paths:
            rel = f.resolve().relative_to(root_dir.resolve())
            cls._insert_into_tree(tree, list(rel.parts), is_file=True)

        # Sort children recursively to keep output stable.
        def sort_node(n: Dict[str, Any]) -> None:
            if "children" not in n:
                return
            n["children"].sort(
                key=lambda x: (x.get("type") != "directory", x.get("name", ""))
            )
            for c in n["children"]:
                sort_node(c)

        sort_node(tree)
        return tree

    def _call_model_for_scan_summary(
        self, repo_tree: Dict[str, Any], meta: Dict[str, Any]
    ) -> None:
        """
        Calls the model for compliance with the "model call per agent" requirement.
        The scan result itself is generated deterministically; the model call is used for a short summary.
        """
        # Keep the prompt small: include only counts and extension breakdown.
        user_instructions = (
            "Summarize the repository scan for automated program repair. "
            "Return a short description (1-3 sentences) of what kinds of source files were found. "
            "Do not propose code changes.\n\n"
            f"Scan meta: {json.dumps(meta, default=str)}"
        )
        _ = self.model.chat(
            self.build_messages(
                {"repo_scan_meta": meta},
                user_instructions,
                include_state_keys=["repo_scan_meta"],
                **self.hyperparameters,
            )
        )

    def run(self, state: dict) -> dict:
        root_dir = BaseAgent.get_repo_root()
        root = root_dir / "."

        # Collect relevant paths
        included_dirs, included_files = self._walk_paths(root)
        repo_tree = self._tree_from_files(".", included_files, root_dir)

        # Compute lightweight meta for prompt + debugging
        meta = {
            "max_depth": self.max_depth,
            "max_file_bytes": self.max_file_bytes,
            "included_files_count": len(included_files),
            "included_dirs_count": len(included_dirs),
        }

        # Save to repo_tree.json
        out_path = root_dir / "repo_tree.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(repo_tree, f, indent=2, ensure_ascii=True)
        
        # TODO rm if not necessary
        # Model call (summary only)
        # try:
        #     self._call_model_for_scan_summary(repo_tree=repo_tree, meta=meta)
        # except Exception:
        #     # Scanner must remain deterministic even if the model is unavailable.
        #     pass

        return {"repo_tree": repo_tree, "repo_scan_meta": meta}
