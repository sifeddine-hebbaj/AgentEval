"""Wrapper that sets MISTRAL_API_KEY and runs the evaluation."""
import os
import sys
from pathlib import Path

# Load .env file if it exists
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)

# Ensure MISTRAL_API_KEY is set
if not os.environ.get('MISTRAL_API_KEY'):
    raise ValueError("MISTRAL_API_KEY environment variable is not set. Please set it in your .env file or environment.")

# Import and run the actual runner
from run_for_eval import main
import json

if __name__ == "__main__":
    try:
        input_data = json.loads(sys.stdin.read())
        response = main(input_data)
        print(json.dumps(response))
    except Exception as e:
        # Print error to stderr for debugging
        print(f"ERROR: {e}", file=sys.stderr)
        # Print stack trace for debugging
        import traceback
        traceback.print_exc()
        sys.exit(1)
