"""Simple Mistral Chat Assistant with full AgentEval SDK instrumentation.

This is a production-ready example showing:
- Complete SDK integration with traces and spans
- Mistral API integration for real LLM calls
- Proper error handling and latency tracking
- Token usage and cost tracking
- Comprehensive tracing of the full agent workflow

Usage:
  - Standalone: python agent.py (requires MISTRAL_API_KEY)
  - Local eval: agenteval run --config agenteval.yaml --local
  - Remote eval: agenteval run --config agenteval.yaml --remote --gate
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# Load environment variables from .env file if it exists
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from agenteval_sdk import Client, span, trace
from mistralai.client import Mistral

# Initialize Mistral client
mistral_client = Mistral(api_key=os.environ.get("MISTRAL_API_KEY"))

# Agent configuration
MODEL = "mistral-small-latest"
MAX_TOKENS = 150
TEMPERATURE = 0.7


def generate_chat_response(user_message: str, system_prompt: Optional[str] = None) -> str:
    """Generate a chat response using Mistral API.
    
    Args:
        user_message: The user's input message
        system_prompt: Optional system prompt to guide the assistant
        
    Returns:
        The assistant's response
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_message})
    
    try:
        response = mistral_client.chat.complete(
            model=MODEL,
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error generating response: {e}"


def generate_chat_response_instrumented(
    user_message: str, 
    system_prompt: Optional[str] = None,
    client: Optional[Client] = None
) -> str:
    """Generate a chat response with full AgentEval tracing.
    
    This function instruments every step of the agent workflow:
    - LLM API call with model name, tokens, and cost
    - Latency tracking
    - Error handling
    
    Args:
        user_message: The user's input message
        system_prompt: Optional system prompt to guide the assistant
        client: AgentEval SDK client for trace collection
        
    Returns:
        The assistant's response
    """
    if client is None:
        # No tracing - just call the function directly
        return generate_chat_response(user_message, system_prompt)
    
    @trace(client=client, name="mistral_chat_assistant")
    def _run(message: str, system: Optional[str]) -> str:
        # Span for the full LLM call
        with span(type="llm_call", name="mistral_chat_completion", model=MODEL) as s:
            try:
                messages = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": message})
                
                response = mistral_client.chat.complete(
                    model=MODEL,
                    messages=messages,
                    max_tokens=MAX_TOKENS,
                    temperature=TEMPERATURE,
                )
                
                assistant_message = response.choices[0].message.content
                
                # Track token usage and cost
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                total_tokens = response.usage.total_tokens
                
                # Mistral small pricing (as of 2024): $0.00002/1K input, $0.00006/1K output
                cost = (prompt_tokens * 0.00002 / 1000) + (completion_tokens * 0.00006 / 1000)
                
                s.set_input(message)
                s.set_output(assistant_message)
                s.set_usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost=cost
                )
                
                return assistant_message
                
            except Exception as e:
                s.status = "error"
                s.error_message = str(e)
                return f"Error: {e}"
    
    return _run(user_message, system_prompt)


def main():
    """Standalone demo of the chat assistant with tracing."""
    # Check for required environment variables
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        print("ERROR: MISTRAL_API_KEY environment variable is required")
        print("Set it with: export MISTRAL_API_KEY=your_key_here")
        print("Or add it to your .env file")
        sys.exit(1)
    
    agenteval_api_key = os.environ.get("AGENTEVAL_API_KEY")
    if not agenteval_api_key:
        print("WARNING: AGENTEVAL_API_KEY not set - running without tracing")
        print("To enable tracing, set: export AGENTEVAL_API_KEY=your_key_here")
        print("To enable tracing, set: export AGENTEVAL_BASE_URL=http://localhost:8000")
        print()
        print("Running chat assistant without AgentEval SDK...")
        print()
        
        # Simple demo without tracing
        response = generate_chat_response(
            "What is the capital of France?",
            "You are a helpful assistant that answers questions concisely."
        )
        print(f"Assistant: {response}")
        return
    
    # With AgentEval tracing
    print("Initializing AgentEval client...")
    client = Client(
        api_key=agenteval_api_key,
        base_url=os.environ.get("AGENTEVAL_BASE_URL", "http://localhost:8000"),
        project="simple-chat-assistant"
    )
    
    print("Sending traced request to chat assistant...")
    response = generate_chat_response_instrumented(
        "What is the capital of France?",
        "You are a helpful assistant that answers questions concisely.",
        client
    )
    
    print(f"Assistant: {response}")
    print()
    print("Flushing traces to AgentEval server...")
    client.flush()
    print("Done! Check the dashboard to view the trace.")


if __name__ == "__main__":
    main()
