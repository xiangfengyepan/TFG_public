"""EvoMas package marker.

Empty by design — submodules import what they need explicitly. The file
exists so Python treats `evomas/` as a regular package, which takes
priority over the sibling `evomas.py` shim in import resolution and keeps
pytest's discovery (`import evomas.tests.test_config`) working when both
the package and the shim live in the repo root.
"""
