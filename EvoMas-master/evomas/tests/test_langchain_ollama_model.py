import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from evomas.config.loader import agent_config_from_block, load_config
from evomas.models.langchain_ollama_model import build_chat_ollama, llm_invoke


@pytest.mark.integration
def test_chat_ollama_basic_call(ollama_required: None) -> None:
    cfg = load_config("evo-star")
    config = agent_config_from_block(cfg["agents"]["ensembler_agent"])
    config.think = False   # disable thinking - we only want to verify connectivity
    config.num_predict = 64
    llm = build_chat_ollama(config)

    response, _ = llm_invoke(llm, [
        SystemMessage(content="Reply with exactly the word OK."),
        HumanMessage(content="Say it."),
    ], agent_name="test")

    content = getattr(response, "content", "")
    if isinstance(content, list):
        content = "".join(
            c.get("text", "") if isinstance(c, dict) else str(c) for c in content
        )
    assert content, "expected non-empty content from ChatOllama"
