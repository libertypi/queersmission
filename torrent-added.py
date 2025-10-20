#!/usr/bin/env python3

import os.path as op

from queersmission.main import main

if __name__ == "__main__":
    main(True, op.join(op.dirname(op.abspath(__file__)), "profile"))
