"""LangGraph checkpoint adapters."""

from langgraph.checkpoint.memory import InMemorySaver


def create_in_memory_checkpointer() -> InMemorySaver:
    """Create a process-local checkpointer; state is lost when the process exits."""
    return InMemorySaver()
