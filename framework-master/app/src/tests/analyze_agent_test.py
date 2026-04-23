from app.src.agents.bug_detector_agent import BugDetectorAgent

def test_analyze_agent_init():
    agent = BugDetectorAgent()
    assert agent is not None