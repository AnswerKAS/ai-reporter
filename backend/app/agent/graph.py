"""LangGraph state machine shared by the dataset and report ReAct agents."""

from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph


class AgentState(TypedDict):
    """One model decision and the observations collected during a turn."""

    observations: list[dict]
    step: int
    action: dict | None
    output: dict | None
    error: str | None


def run_graph(
    decide: Callable[[list[dict]], dict],
    use_tool: Callable[[dict], dict],
    finish: Callable[[dict], tuple[dict | None, dict | None]],
    *,
    max_steps: int,
) -> AgentState:
    """Run model, tool and finalizer nodes until a checked answer or step limit."""

    def model_node(state: AgentState) -> dict:
        """Choose one ReAct action from the accumulated observations."""
        try:
            return {'action': decide(state['observations']), 'step': state['step'] + 1}
        except Exception as exc:
            return {'error': str(exc), 'step': state['step'] + 1}

    def tool_node(state: AgentState) -> dict:
        """Execute a named tool and append its result or error to state."""
        try:
            observation = use_tool(state['action'] or {})
        except Exception as exc:
            observation = {'error': str(exc)}
        return {'observations': [*state['observations'], observation]}

    def final_node(state: AgentState) -> dict:
        """Accept a verified final answer or ask the model to repair it."""
        try:
            output, observation = finish(state['action'] or {})
        except Exception as exc:
            output, observation = None, {'error': str(exc)}
        if output is not None:
            return {'output': output}
        return {'observations': [*state['observations'], observation or
                                 {'error': 'Ответ не прошёл проверку.'}]}

    def after_model(state: AgentState) -> str:
        """Route an action to its tool or finalizer, stopping on errors."""
        if state['error'] or state['action'] is None:
            return END
        if 'final' in state['action'] or 'definition' in state['action']:
            return 'final'
        return 'tool'

    def after_step(state: AgentState) -> str:
        """Continue reasoning while work remains and the step budget allows."""
        return END if state['output'] is not None or state['step'] >= max_steps else 'model'

    workflow = StateGraph(AgentState)
    workflow.add_node('model', model_node)
    workflow.add_node('tool', tool_node)
    workflow.add_node('final', final_node)
    workflow.add_edge(START, 'model')
    workflow.add_conditional_edges('model', after_model)
    workflow.add_conditional_edges('tool', after_step)
    workflow.add_conditional_edges('final', after_step)
    return workflow.compile().invoke({
        'observations': [], 'step': 0, 'action': None,
        'output': None, 'error': None,
    })
