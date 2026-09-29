"""Entry point: `python run.py [files...]` (also the PyInstaller script)."""

import multiprocessing
import sys

from cocseq.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main(sys.argv))
