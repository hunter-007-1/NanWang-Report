from langchain.tools import tool


@tool(
    "calculator",
    description="Performs arithmetic calculations. Use this for any math problems.",
)
def calculator(expression: str) -> str:
    """Evaluate mathematical expressions."""
    return str(eval(expression))
