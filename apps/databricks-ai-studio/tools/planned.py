from backend.tool_registry import ToolContext, ToolError


def not_available(ctx: ToolContext, **_):
    raise ToolError("Cet outil n'est pas encore disponible dans le MVP.")
