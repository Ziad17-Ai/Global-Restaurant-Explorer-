"""Module entry point enabling `python -m pipeline.etl ...`."""

import sys
from pipeline.etl.cli import main

if __name__ == "__main__":
    sys.exit(main())
