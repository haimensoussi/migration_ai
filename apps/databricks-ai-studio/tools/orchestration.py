"""Outil de délégation multi-agents (utilisé uniquement par les agents superviseurs)."""
from backend.tool_registry import ToolContext, ToolError


def ask_agent(ctx: ToolContext, agent: str, question: str) -> dict:
    if not callable(getattr(ctx, "delegate", None)):
        raise ToolError("Délégation indisponible : cet agent n'est pas configuré comme superviseur.")
    return ctx.delegate(agent, question)
