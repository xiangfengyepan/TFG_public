# Note

## Repository attributes

### Publication of an article : URL or none

- Readme.md

---

### Framework used : list

- look in README.md, requirements.txt, or .py files for mentions of frameworks
- e.g. langchain, langgraph, use their own scripts, the project is a framework itself -Moatless, Openhand-
- use regex to find matches in .py files: ``` (?:import|from)\s+.*(?:langchain).* ```
where u can change langchain for any of these framework: ```metagpt|langgraph|spade|aiomas|pyMAS|mesa|pettingzoo|magent|langchain|llama-index|simpy|pydantic-ai```

```(?:import|from)\s+.*(?:metagpt|langgraph|spade|aiomas|pyMAS|mesa|pettingzoo|magent|langchain|llama.index|simpy|pydantic_ai).*```

- update the settings.json "search.exclude": variable.
- search for dependency files e.g. requirements.txt

#### List of frameworks

- metagpt
- langgraph
- spade
- aiomas
- pyMAS
- mesa
- pettingzoo
- magent
- langchain
- llama-index
- simpy
- pydantic-ai

---

### Has Agents? : bool

- look in .py files

---

### # Agents : int

- look in .py files, count the number of agents created

---

### Dependency graph: file

- Export SBOM file (Json) at <https://github.com/..../network/dependencies>
- GitHub > Insights > Dependency graph

---

### Topology : file or text

- find an image or file that shows the architecture or topology of the system, or look for descriptions in README.md or documentation

---

### Programming language : list

- look in GitHub repository for the language used
- e.g. python

---

### Autonomy : range(1, 5) and Description

- Three categories of autonomy:
  - 5: Full autonomy: Single Agent or Multi-Agent system that decide the execution of the agents by themselves without any software (workflow).
  - 1. Semi-autonomy: Multi-Agent system that has some type of restriction on the workflow of agents communication but still can decide the execution without any software (workflow) but following those restrictions.
  - 1. Orchestrated: Multi-Agent system that has a software (workflow) or human that decide the execution of the agents.

- find if the system is autonomous or not, look for mentions in README.md or documentation

---
---

## Agent attributes

- Name: text
  - Agent name
- Short Description : text
  - See README.md or documentation
- Agent in the repo : URL or none
  - URL of the agent class in repository
- ... Prompts : URL or none
  - URL of the prompts that the Agent uses
- ... Tool: URL or text
  - URL of the tools that the Agent uses
