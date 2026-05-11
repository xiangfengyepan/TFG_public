from typing import Any

from evomas.agents.types.helper_proxy import HelperProxyAgent


class EnsemblerAgent(HelperProxyAgent):
    name = "ensembler_agent"

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # Edge-driven input: the validator forwards a bundle
        # `{patches, validations}` so we can score-and-pick from one slot.
        bundle: dict[str, Any] = state.get(self.predecessor_name or "") or {}
        patches: list[str] = list(bundle.get("patches") or [])
        results: list[dict[str, Any]] = list(bundle.get("validations") or [])

        if not patches:
            self.logger.warning("ensembler: no candidate patches; final_patch=''")
            return {self.name: ""}

        if not results or len(results) != len(patches):
            self.logger.warning("ensembler: missing validation results; using first non-empty")
            return {self.name: self._first_non_empty(patches)}

        scored = sorted(
            zip(patches, results),
            key=lambda pr: (
                pr[1].get("score", 0),
                pr[1].get("applies", False),
                pr[1].get("flake8_ok", False),
                pr[1].get("review_pass", False),
            ),
            reverse=True,
        )
        best_patch, best_result = scored[0]
        self.logger.info(
            "ensembler picked candidate %d (score=%s applies=%s flake8=%s review=%s)",
            best_result.get("patch_idx"),
            best_result.get("score"),
            best_result.get("applies"),
            best_result.get("flake8_ok"),
            best_result.get("review_pass"),
        )
        if best_result.get("score", 0) > 0 and best_patch.strip():
            return {self.name: best_patch}

        # Only fall back to a non-empty patch when it actually applies.
        # Submitting an unapplicable patch causes harness EvaluationError;
        # an empty patch is safely skipped as unresolved.
        applies_map = {r.get("patch_idx", i): r.get("applies", False) for i, r in enumerate(results)}
        fallback = next(
            (p for i, p in enumerate(patches) if p.strip() and applies_map.get(i, False)),
            "",
        )
        self.logger.info(
            "ensembler: all candidates scored 0; fallback applies=%s len=%d",
            bool(fallback), len(fallback),
        )
        return {self.name: fallback}

    @staticmethod
    def _first_non_empty(patches: list[str]) -> str:
        for p in patches:
            if p and p.strip():
                return p
        return ""
