#!/usr/bin/env python3
"""Placeholder. Replace with tools/insert_atoms.py from the delivery tarball.

This tree is a read-only delivery candidate. Do not insert into
data/teaching.db or mutate production learner state.
"""
from __future__ import annotations

import sys


def main() -> int:
    print(
        "insert_atoms.py is a placeholder until zhou_comm_atoms_delivery.tar.gz "
        "is extracted into data/zhou_comm/. Refusing to write.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
