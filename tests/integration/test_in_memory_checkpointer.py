from typing import TypedDict

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from infrastructure.state.checkpointing import create_in_memory_checkpointer

pytestmark = pytest.mark.integration


class CounterState(TypedDict):
    count: int


def increment(state: CounterState) -> CounterState:
    return {"count": state["count"] + 1}


def build_counter_graph(
    checkpointer: InMemorySaver,
) -> CompiledStateGraph[CounterState, None, CounterState, CounterState]:
    builder = StateGraph(CounterState)
    builder.add_node("increment", increment)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    return builder.compile(checkpointer=checkpointer)


def test_checkpoint_persists_state_for_the_process_lifetime() -> None:
    checkpointer = create_in_memory_checkpointer()
    first_graph = build_counter_graph(checkpointer)
    second_graph = build_counter_graph(checkpointer)
    config: RunnableConfig = {"configurable": {"thread_id": "thread-1"}}

    assert first_graph.invoke({"count": 0}, config) == {"count": 1}
    assert second_graph.invoke({"count": 10}, config) == {"count": 11}
    assert second_graph.get_state(config).values == {"count": 11}


def test_checkpoints_do_not_survive_a_new_checkpointer_instance() -> None:
    config: RunnableConfig = {"configurable": {"thread_id": "thread-1"}}
    first_graph = build_counter_graph(create_in_memory_checkpointer())
    first_graph.invoke({"count": 0}, config)

    restarted_graph = build_counter_graph(create_in_memory_checkpointer())

    assert restarted_graph.get_state(config).values == {}
