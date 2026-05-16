import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from evomas.config.loader import agent_config_from_block, load_config
from evomas.models import build_chat
from evomas.models.langchain_ollama_model import llm_invoke


@pytest.mark.integration
def test_chat_ollama_basic_call(ollama_required: None) -> None:
    cfg = load_config("chain")
    config = agent_config_from_block(cfg["agents"]["finalizer"])
    config.think = False   # disable thinking - we only want to verify connectivity
    config.num_predict = 64
    # build_chat strips the `ollama/` prefix before dispatching to
    # build_chat_ollama, so the config can carry the prefixed name uniformly.
    llm = build_chat(config)

    response, _, usage = llm_invoke(llm, [
        SystemMessage(content="Reply with exactly the word OK."),
        HumanMessage(content="Say it."),
    ], agent_name="test")

    content = getattr(response, "content", "")
    if isinstance(content, list):
        content = "".join(
            c.get("text", "") if isinstance(c, dict) else str(c) for c in content
        )
    assert content, "expected non-empty content from ChatOllama"
    # Token tracking is now part of the llm_invoke contract — every Ollama
    # response should carry at least input/output counters via the
    # streaming finalizer.
    assert usage.get("total", 0) > 0, f"expected non-zero token total, got {usage}"
