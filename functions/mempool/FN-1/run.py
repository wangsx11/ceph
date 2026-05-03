#!/usr/bin/env python3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.runner import main_entry

main_entry("mempool", "FN-1", __file__)

