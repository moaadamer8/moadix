#!/usr/bin/python3
"""Operator tool: create .sdlc/ in a product repo.  sdlc_init.py <repo> <product-id>

Increment 2: the typed command `INIT <product-id> <code>` replaces this for the
operator (it also records ledger line 1). This tool remains for the installer's
canary and the tests. Run from a terminal (the PreToolUse gate denies the agent
any command naming the gate's files). Creates product.yaml, an empty ledger,
phase.yaml, knowledge.md, untested.yaml and evidence/.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gate import state  # noqa: E402

if len(sys.argv) != 3:
    sys.exit("usage: sdlc_init.py <repo> <product-id>")
state.init_product(os.path.realpath(sys.argv[1]), sys.argv[2])
print("created %s/.sdlc for product %s" % (os.path.realpath(sys.argv[1]), sys.argv[2]))
