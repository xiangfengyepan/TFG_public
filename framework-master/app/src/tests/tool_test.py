import json
from app.src.tools.tool_registry import ToolRegistry

# IMPORTANT!
# We import the modules so that the @ToolRegistry.tool decorators execute
# and the tools are registered in ToolRegistry.tools
import app.src.tools.code_tools
import app.src.tools.repo_tools
import app.src.tools.terminal_tool

from dotenv import load_dotenv


def run_test(test_name: str, tool_name: str, args: dict):
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}")
    print(f"TOOL: {tool_name}")
    print(f"ARGS: {json.dumps(args)}")
    print(f"{'-'*60}")

    try:
        result = ToolRegistry.execute(tool_name, args)

        print("RESULT:")
        if isinstance(result, (dict, list)):
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(result)

    except Exception as e:
        print(f"UNEXPECTED ERROR: {e}")


def main():
    load_dotenv(override=True)
    print("Starting LangChain tools test suite in Docker...\n")

    run_test(
        test_name="Run terminal command",
        tool_name="terminal_tool",
        args={"command": "ls /"},
    )

    # run_test(
    #     test_name="Create a test file",
    #     tool_name="write_file_tool",
    #     args={
    #         "path": "dummy_test_file.txt",
    #         "content": "Hello from the Docker container!\nThis is a write test.",
    #     },
    # )

    # run_test(
    #     test_name="Read the test file",
    #     tool_name="read_file_tool",
    #     args={"path": "dummy_test_file.txt"},
    # )

    # # run_test(
    # #     test_name="List files (non-recursive)",
    # #     tool_name="list_files_tool",
    # #     args={"path": ".", "recursive": False, "max_files": 10},
    # # )

    # run_test(
    #     test_name="Search text in code",
    #     tool_name="search_code_tool",
    #     # We search for the phrase "Hello from" assuming it will find the .txt we just created
    #     args={"query": "Hello from", "path": ".", "use_regex": False},
    # )

    # run_test(
    #     test_name="Read multiple files at once",
    #     tool_name="read_files_batch_tool",
    #     args={"paths": ["dummy_test_file.txt", "Dockerfile"]},
    # )

    print(f"\n{'='*60}")
    print("TEST SUITE FINISHED")


if __name__ == "__main__":
    main()
