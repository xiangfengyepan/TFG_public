from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from app.src.agents.base_agent import BaseAgent
from pydantic import BaseModel, Field

from app.src.tools.tool_registry import ToolRegistry
from paths import PATCH_GENERATOR_AGENT_JSON


class GeneratedPatch(BaseModel):
    file_path: str = Field(
        description="Relative path to the file within the repository to patch."
    )
    new_content: str = Field(description="The full updated content for the file.")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence in the correctness of the patch."
    )
    notes: str = Field(
        default="", description="Short explanation of what changed and why."
    )


class PatchGenerationResponse(BaseModel):
    patches: List[GeneratedPatch]
    summary: str = Field(default="")


class PatchGeneratorAgent(BaseAgent):
    """
    Generates code patches for detected issues and applies them to the repository.
    """

    # TODO update
    LOW_CONFIDENCE_THRESHOLD = 0.6

    def __init__(self):
        with open(PATCH_GENERATOR_AGENT_JSON, "r") as f:
            self.hyperparameters = json.load(f)
        super().__init__()

    # TODO check
    def _read_file(self, rel_path: str, *, max_chars: int = 20000) -> str:
        max_bytes = max_chars * 2
        try:
            text = ToolRegistry.execute(
                name="read_file_tool", args={"path": rel_path, "max_bytes": max_bytes}
            )
        except Exception:
            text = ""
        if len(text) > max_chars:
            return text[: max_chars - 50] + "\n...<TRUNCATED>..."
        return text

    @staticmethod
    def _ensure_todo_for_low_confidence(new_content: str) -> str:
        if "# TODO:" in new_content:
            return new_content
        # Fallback: keep the TODO visible at the top of the file to force manual review.
        # (The model is instructed to place TODOs directly above uncertain code regions.)
        return (
            "# TODO: Low-confidence automated patch; please review the change carefully.\n\n"
            + new_content
        )

    def run(self, state: dict) -> dict:
        issues = state.get("issues") or []
        if not issues:
            return {
                "patches": [],
                "patch_generation_raw": "",
                "patch_generation_skipped": True,
            }

        # Sort issues: high -> medium -> low
        severity_rank = {"high": 0, "medium": 1, "low": 2}
        issues_sorted = sorted(
            issues,
            key=lambda x: severity_rank.get(str(x.get("severity", "low")).lower(), 2),
        )
        issues_sorted = issues_sorted[:6]

        generated_patches: List[Dict[str, Any]] = []
        raw_outputs: List[str] = []

        # TODO pass al issues so no need of loop for
        for issue in issues_sorted:
            rel_path = issue.get("file_path")
            if not rel_path:
                continue

            original_content = self._read_file(rel_path)
            if not original_content.strip():
                continue

            user_instructions = (
                "You are generating a code patch for automated program repair.\n"
                "Task: Fix the described bug/issue in the given file.\n\n"
                "Rules:\n"
                "1. Output JSON that matches the required schema.\n"
                "2. Provide the updated FULL file content in `new_content`.\n"
                "3. Assign a numeric `confidence` between 0 and 1.\n"
                "4. If confidence is LOW (< 0.6), you MUST include at least one '# TODO:' comment directly above any uncertain code region(s) you add/modify.\n"
                "5. Do not introduce unrelated refactors.\n\n"
                "6. If the issue described is already resolved in the current file, return the file unchanged.\n"
                f"Issue description:\n{issue}\n\n"
                f"Current file content ({rel_path}):\n{original_content}"
            )

            messages = self.build_messages(
                state,
                user_instructions,
                include_state_keys=["task_description", "repo_tree", "issues"],
            )

            raw_text: str = ""
            try:
                response = self.model.chat(
                    messages=messages,
                    response_format=PatchGenerationResponse,
                    **self.hyperparameters,
                )
                raw_text = self.parse_text_output(
                    getattr(response.message, "content", "") if response else ""
                )
                parsed = self.extract_json(raw_text) if raw_text else None
                if isinstance(parsed, dict) and parsed.get("patches"):
                    for p in parsed["patches"]:
                        # Ensure TODO comment if low confidence
                        try:
                            conf = float(p.get("confidence", 1.0))
                        except Exception:
                            conf = 1.0
                        
                        # TODO this may not be needed
                        if conf < self.LOW_CONFIDENCE_THRESHOLD:
                            p["new_content"] = self._ensure_todo_for_low_confidence(
                                p.get("new_content", "")
                            )
                        generated_patches.append(p)
                    raw_outputs.append(raw_text)
                    continue
            except Exception:
                pass
            
            # TODO rm this if not needed
            # If the model fails, do a minimal "no-op" patch entry instead of guessing code changes.
            generated_patches.append(
                {
                    "file_path": rel_path,
                    # Avoid writing truncated content back to disk.
                    "new_content": None,
                    "confidence": 0.0,
                    "notes": "Patch generation failed or returned invalid JSON; no changes applied for this issue.",
                    "skip_apply": True,
                }
            )
            raw_outputs.append(raw_text)

        # Apply patches to the working directory.
        applied_files = set()
        applied_patches: List[Dict[str, Any]] = []
        for patch in generated_patches:
            rel_path = patch.get("file_path")
            if not rel_path:
                continue
            if patch.get("skip_apply"):
                continue
            # If multiple issues touch the same file, last one wins (deterministic).
            if rel_path in applied_files:
                # Overwrite by applying again (handled by write_file_tool).
                pass
            new_content = patch.get("new_content", "")
            if not isinstance(new_content, str):
                continue
            ToolRegistry.execute(
                name="write_file_tool", args={"path": rel_path, "content": new_content}
            )

            applied_files.add(rel_path)
            applied_patches.append(patch)

        return {
            "patches": applied_patches,
            "patch_generation_raw": "\n\n".join([s for s in raw_outputs if s]),
            "patches_applied": [p.get("file_path") for p in applied_patches],
        }
