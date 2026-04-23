from pathlib import Path

FRAMEWORK_BASE_DIR = Path(__file__).parent.resolve()

WORKFLOW_JSON = FRAMEWORK_BASE_DIR / "app" / "agent_topology" / "workflow_data.json"

AGENT_CONFIG_DIR = FRAMEWORK_BASE_DIR / "app" / "agent_config"
DEFAULT_AGENT_CONFIG = AGENT_CONFIG_DIR / "default.json"
LOCALIZE_AGENT_JSON = AGENT_CONFIG_DIR / "localize_agent.json"
PATCH_GENERATOR_AGENT_JSON = AGENT_CONFIG_DIR / "patch_generator_agent.json"
BASE_AGENT_JSON = AGENT_CONFIG_DIR / "base_agent.json"
BUG_DETECTOR_AGENT_JSON = AGENT_CONFIG_DIR / "bug_detector_agent.json"
CONTEXT_COLLECTOR_AGENT_JSON = AGENT_CONFIG_DIR / "context_collector_agent.json"
ISSUE_PRIORITIZER_AGENT_JSON = AGENT_CONFIG_DIR / "issue_prioritizer_agent.json"
PATCH_GENERATOR_AGENT_JSON = AGENT_CONFIG_DIR / "patch_generator_agent.json"
REPO_SCANNER_AGENT_JSON = AGENT_CONFIG_DIR / "repo_scanner_agent.json"
VALIDATOR_AGENT_JSON = AGENT_CONFIG_DIR / "validator_agent.json"


GENERATED_TESTS_DIR = FRAMEWORK_BASE_DIR / "app" / "generated_tests"
ENV_DIR = FRAMEWORK_BASE_DIR / "app" / ".env"
