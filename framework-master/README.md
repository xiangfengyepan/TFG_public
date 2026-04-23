# Framework

. Use an agent to control the parameter of other agents: temperature, think, etc

- Use sandbox for execution
- use langchain limit LLM call cicle

- interface
- integrate agents from other MAS

- patch generator
- validator patch4

- Use pynguin to auto generate test

```shell
$env:PYNGUIN_DANGER_AWARE="true"
python generate_tests.py
```

- Ollama version
```ollama version is 0.18.0```
- Ollama docs: <https://github.com/ollama/ollama/blob/main/docs/api.md>
- Ollama modelfile.mdx: <https://github.com/ollama/ollama/blob/main/docs/modelfile.mdx#valid-parameters-and-values>
- format: json or schema (works bad without thinking)

- Ollama models <https://ollama.com/search>:
  - fervent_mcclintock/Qwen2.5-RP-test1-7B:Q4_K_S
  - qwen3.5:9b
  - deepseek-r1:8b

- Prompt template Go Template <https://pkg.go.dev/text/template>

## Pre-requisites

- computer CPU AMD Ryzen 5 5600G or higher (RAM>= 16GB) (ROM enogh for the ollma models see docs)
- windos or linux
- python (recomaneded 3.12)
- ollama
- docker (optional)


## Install Windows

Install python 3.12 <https://www.python.org/downloads/windows/>

``` shell
cp .env.example .env #set the TARGET_ROOT_DIR to the bug root folder

```

```shell
setup.ps1
script/run.ps1
```

## Docker

```shell
docker build --no-cache -t swe-bench .
docker run -it --rm swe-bench bash
```

## Citation

## License

## Privacy

## Acknowledge

