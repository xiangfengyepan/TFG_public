"""Backwards-compatible re-export for the dynamic state factory.

The original module exposed a hardcoded `EvomasState` TypedDict. The state schema is
now built from the unified config — see `evomas.core.workflow.state_factory`.
"""
from evomas.core.workflow.state_factory import build_initial_state, build_state_class

__all__ = ["build_initial_state", "build_state_class"]
