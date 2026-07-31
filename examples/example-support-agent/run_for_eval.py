"""Stdin/stdout shell-runner adapter for the CLI's --local gate mode.

The CLI's shell-runner protocol (see backend/agenteval_cli/main.py
_make_runner) pipes the test case's `input` as JSON on stdin and
expects JSON-encoded output on stdout. This tiny wrapper adapts
agent.py's plain Python function to that protocol.
"""
import json
import sys

from agent import answer_support_query

if __name__ == "__main__":
    query = json.loads(sys.stdin.read())
    result = answer_support_query(query)
    print(json.dumps(result))
