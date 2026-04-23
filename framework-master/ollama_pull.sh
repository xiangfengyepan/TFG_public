#!/bin/sh
set -e

# Pull models at image build time.
# Extend this file with additional `ollama pull <model>` lines as needed.

ollama pull qwen3.5:9b

# ollama pull qwen3.5:4b
# ollama pull qwen3-vl:8b
# ollama pull gpt-oss:20b

