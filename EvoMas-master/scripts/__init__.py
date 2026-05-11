"""Top-level entry-point scripts wrapped by `evomas.cli`.

The `evomas` console command (and the repo-root `evomas.py` shim) dispatch
to `generate_swebench_instances.py`, `generate_evomas_predictions.py`, and
`run_swebench_evaluation.py` in this directory. The package marker exists
so `api/server.py` can do `from scripts.generate_swebench_instances import
build_instances` without `scripts/` being interpreted as a namespace
package.
"""
