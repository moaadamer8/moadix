"""Run one ported v1 validator as __main__: `_launch.py <module.py> [args...]`.

gate/validate.py starts every validator through this file so a test fixture's
guard (gate/_testguard.py, present only in fixtures) also watches the
validators. In an installed gate it only runs the module.
"""
import contextlib
import importlib
import os
import runpy
import sys

GATE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.dirname(GATE))
with contextlib.suppress(ImportError):
    importlib.import_module("gate._testguard")  # exists only in test fixtures
target = os.path.realpath(sys.argv[1])
sys.argv = [target] + sys.argv[2:]
sys.path.insert(0, os.path.dirname(target))
runpy.run_path(target, run_name="__main__")
