#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from pipeline_config import run_pipeline

if __name__ == "__main__":
    run_pipeline()