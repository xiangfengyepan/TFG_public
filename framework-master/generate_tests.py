from paths import GENERATED_TESTS_DIR

import os
import subprocess
import sys


PROJECT_DIR = "src"

OUTPUT_DIR = GENERATED_TESTS_DIR


def find_python_files(root_dir):
    py_files = []
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".py") and not file.startswith("test_"):
                full_path = os.path.join(root, file)
                py_files.append(full_path)
    return py_files


def run_pynguin_on_file(py_file):
    module_path = py_file.replace("\\", ".").replace("/", ".").replace(".py", "")

    print(f"\n[Pynguin] Generating tests for: {module_path}")

    cmd = [
        sys.executable,
        "-m",
        "pynguin",
        "--project-path",
        PROJECT_DIR,
        "--output-path",
        OUTPUT_DIR,
        "--module-name",
        module_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[ERROR] Failed for {module_path}")
        print(result.stderr)
    else:
        print(f"[OK] Tests generated for {module_path}")


def main():
    py_files = find_python_files(PROJECT_DIR)

    print(f"Found {len(py_files)} Python files.")

    for py_file in py_files:
        run_pynguin_on_file(py_file)


if __name__ == "__main__":
    main()
