# TODO

- Use sandbox for execution (docker for terminal tools) -> using docker
- allow list for terminal tools
- interface graph
- add hyperparameter to agent chat call

<!-- - use langchain limit LLM call cicle -->
- integrate agents from other MAS


- Use pynguin to auto generate test
- use pytest for testing

## Prompt

You are an expert in multi-agent systems, LangGraph, and automated program repair (APR).

Your task is to build a complete multi-agent APR framework inside this repository.

---

## 1. Project Structure

Create the following folders and files:

## agents/

- `base_agent.py` — Base class defining shared agent interface, model calls, and context handling.  
- `repo_scanner_agent.py` — Scans the repository and generates a cleaned JSON tree representation.  
- `bug_detector_agent.py` — Analyzes code to detect potential bugs and problematic patterns.  
- `patch_generator_agent.py` — Generates code fixes with confidence levels and optional TODO comments.  
- `validator_agent.py` — Validates patches and flags those requiring manual review.  

## tools/

- `repo_tools.py` — Utilities for navigating and querying the repository structure.  
- `code_tools.py` — Utilities for reading, writing, searching, and modifying code files.  
- `tool_registry.py` — Registers and exposes all tools to the model for tool-based execution.  

## core/

- `workflow.py` — Defines the LangGraph workflow connecting all agents into an APR pipeline.  

---

## 2. Model Integration

All agents MUST call the model via:
@models/ollama_model.py

Use the method:

- tool_chat(...) when tools are needed
- chat(...) otherwise

---

## 3. Agents Design

Each agent must be a class with:

- `run(state: dict) -> dict`

### Agents

1. RepoScannerAgent
   - Builds a full directory tree from '.'
   - Saves it to: `repo_tree.json`
   - Returns it in state

2. BugDetectorAgent
   - Takes repo_tree + code snippets
   - Identifies potential bugs or failing areas

3. PatchGeneratorAgent:
    - Generates fixes for detected issues
    - Assigns a confidence level to each fix
    - If confidence is low:
    - Inserts TODO comments in the generated code

4. ValidatorAgent
   - Validates patch correctness (basic static checks or re-analysis)
   - Say if the bug is solve or not and justifies it.

---

## 4. Tools (LangChain)

Create tools in `tools/` using LangChain:

Examples:

- read_file_tool(path)
- write_file_tool(path, content)
<!-- - list_files_tool(path) -->
- search_code_tool(query)
**You may add more**

Register ALL tools in:
@tools/tool_registry.py

Ensure:

- Compatible with ollama_model.tool_chat
- Tools are callable by name

---

## 5. Repo Tree Generator

RepoScannerAgent must:

- Walk directory using `os.walk`
- Build JSON structure:

{
  "name": ".",
  "type": "directory",
  "children": [...]
}

- Save to `repo_tree.json`

### Exclusions (VERY IMPORTANT)

The scanner MUST ignore:

#### Directories

**For example:**

- venv/
- .venv/
- env/
- node_modules/
- .git/
- \_\_pycache\_\_/
- dist/
- build/
- .mypy_cache/
- .pytest_cache/

#### File types

**For example:**

- .pyc
- .pyo
- .log
- .lock
- .DS_Store

#### Hidden files and folders

- Any file/folder starting with "."

### Additional Rules

- Limit depth if needed (e.g., max depth = 5) to avoid huge trees
- Optionally skip very large files (>1MB)
- Only include relevant source files:
  - .py, .js, .ts, .java, .cpp, etc.

### Goal

Keep the repo tree:

- Clean
- Lightweight
- Relevant for code analysis

---

## 6. LangGraph Workflow

Implement in `core/workflow.py`:

Use LangGraph to define a pipeline:

RepoScannerAgent
    → BugDetectorAgent
    → PatchGeneratorAgent
    → ValidatorAgent

State should include:
{
"repo_tree": ...,
"issues": ...,
"patches": ...,
"validation": ...
}

---

## 7. Context Handling

Each agent MUST:

- Receive full task context:
  "You are fixing bugs in a repository using automated program repair."

- Include:
  - repo_tree (if available)
  - previous outputs from state

This avoids context loss.

---

## 8. Code Quality Requirements

- Use clean OOP design
- Add docstrings
- Ensure imports are correct
- Make everything runnable

---

## 9. Output Requirement

Generate ALL code files fully implemented.
Do NOT leave placeholders or TODOs.

## 10. Code Generation Review Requirement

When generating code:

- If any part of the implementation is uncertain, incomplete, or based on assumptions:
  - Add a `# TODO:` comment explaining what needs manual review.

### Rules

- Place the TODO directly above the relevant code
- Be specific about what is uncertain
- Prefer adding a TODO rather than guessing unclear behavior
- Do NOT leave silent assumptions in the code

### Example

```python
# TODO: Verify error handling logic for edge cases (not fully specified)

def process_data(data):
    ...
```
