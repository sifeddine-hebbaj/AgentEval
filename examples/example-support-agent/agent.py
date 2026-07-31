"""A small, realistic reference agent, fully instrumented with the
AgentEval SDK. Simulates a customer-support agent that retrieves a
canned "knowledge base" snippet and composes a response.

This file is used in two ways:
  1. Standalone demo: `python agent.py` runs it once against a sample
     query and flushes a trace to a local AgentEval server.
  2. As a CLI runner: `agenteval run --config agenteval.yaml --local`
     imports `answer_support_query` directly (see agenteval.yaml's
     `runner: examples.example-support-agent.agent:answer_support_query`).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from agenteval_sdk import Client, span, trace  # noqa: E402

KB = {
    "refund": "Refunds are processed within 5-7 business days to the original payment method.",
    "password": "To reset your password, click 'Forgot password' on the login screen and follow the emailed link.",
    "shipping": "Standard shipping takes 3-5 business days; express shipping takes 1-2 business days.",
    "cancel": "You can cancel your subscription anytime from Account Settings > Subscription > Cancel.",
}


def _retrieve(query: str) -> str:
    query_lower = query.lower()
    for keyword, doc in KB.items():
        if keyword in query_lower:
            return doc
    return "No specific documentation found for this query."


def _generate(query: str, context: str) -> str:
    # A real agent would call an LLM here. Kept as a deterministic
    # template so the example runs with zero API keys required.
    return f"Based on our documentation: {context}"


def answer_support_query(query: str) -> str:
    """The function CI/the CLI calls as the 'runner' for evaluation."""
    context = _retrieve(query)
    return _generate(query, context)


def answer_support_query_instrumented(query: str, client: Client) -> str:
    """Same logic, but wrapped with full SDK tracing -- this is what a
    production agent actually looks like end-to-end.
    """

    @trace(client=client, name="support_agent")
    def _run(q: str) -> str:
        with span(type="retrieval", name="fetch_kb_docs") as s:
            context = _retrieve(q)
            s.set_output(context)

        with span(type="llm_call", name="generate_response", model="template-v1") as s:
            response = _generate(q, context)
            s.set_output(response)
            s.set_usage(prompt_tokens=len(q.split()), completion_tokens=len(response.split()), cost=0.0002)

        return response

    return _run(query)


if __name__ == "__main__":
    api_key = os.environ.get("AGENTEVAL_API_KEY")
    if api_key:
        client = Client(api_key=api_key, base_url=os.environ.get("AGENTEVAL_BASE_URL", "http://localhost:8000"))
        result = answer_support_query_instrumented("How do I get a refund?", client)
        print(result)
        client.flush()
        print("Trace flushed to AgentEval.")
    else:
        print(answer_support_query("How do I get a refund?"))
        print("(Set AGENTEVAL_API_KEY to also send a trace to a running AgentEval server.)")
