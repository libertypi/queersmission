#!/usr/bin/env python3

import os.path as op

from queersmission.main import main

if __name__ == "__main__":
    main(False, op.abspath(op.dirname(__file__)))
