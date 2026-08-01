"""Stdin/stdout shell-runner adapter for the CLI's evaluation mode.

The CLI's shell-runner protocol (see backend/agenteval_cli/main.py)
pipes the test case's `input` as JSON on stdin and expects JSON-encoded
output on stdout. This wrapper adapts the agent.py function to that protocol.
"""
import json
import sys
import os
from pathlib import Path

# Load environment variables from .env file if it exists
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from agent import generate_chat_response_instrumented


def main(input_value: dict) -> str:
    """Main function that can be imported by the CLI.
    
    Args:
        input_value: Dictionary with 'input' and optional 'system_prompt'
        
    Returns:
        The assistant's response as a string
    """
    user_message = input_value.get("input", "")
    system_prompt = input_value.get("system_prompt", "You are a helpful assistant that answers questions concisely.")
    
    return generate_chat_response_instrumented(user_message, system_prompt, client=None)


if __name__ == "__main__":
    # Read the input from stdin (JSON format)
    input_data = json.loads(sys.stdin.read())
    
    # For CLI evaluation, we don't use the AgentEval SDK client
    # (the CLI handles tracing in a different way)
    try:
        response = main(input_data)
    except Exception as e:
        # Return error as JSON
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    
    # Output the response as JSON
    print(json.dumps(response))
