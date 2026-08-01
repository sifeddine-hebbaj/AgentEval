"""Wrapper script that loads .env and runs the evaluation runner."""
import os
import sys
from pathlib import Path

# Load environment variables from .env file
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)

# Import and run the actual runner
from run_for_eval import *

if __name__ == "__main__":
    # This won't be called directly, but kept for compatibility
    pass
