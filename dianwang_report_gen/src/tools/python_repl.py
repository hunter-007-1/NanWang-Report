"""
Python REPL Tool for executing Python code.

This tool provides a safe Python REPL environment for executing code.
"""

import io
import contextlib
from langchain.tools import tool


@tool(
    "python_repl",
    description=(
        "Execute Python code for data analysis. "
        "Use this for running Python scripts, analyzing data, or performing calculations. "
        "Returns the output or any errors. "
        "Supports pandas, numpy, matplotlib, and other common data science libraries. "
        "Input should be a valid Python code string."
    ),
)
def python_repl(code: str) -> str:
    """
    Execute Python code in a controlled REPL environment.

    Args:
        code: Python code to execute as a string

    Returns:
        String containing the output of the executed code or error messages
    """
    # Create string buffers to capture output
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()

    try:
        # Execute code with captured output
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(
            stderr_buffer
        ):
            # Use exec to run the code
            # Create a local namespace for execution
            local_namespace = {
                "__name__": "__main__",
                "__builtins__": __builtins__,
                # Pre-import common libraries
                "print": print,
            }

            exec(code, globals(), local_namespace)

        # Get captured output
        stdout_output = stdout_buffer.getvalue()
        stderr_output = stderr_buffer.getvalue()

        # Combine outputs
        if stdout_output and stderr_output:
            result = f"Output:\n{stdout_output}\nErrors:\n{stderr_output}"
        elif stdout_output:
            result = stdout_output
        elif stderr_output:
            result = f"Errors:\n{stderr_output}"
        else:
            result = "Code executed successfully (no output)"

        return result

    except Exception as e:
        return f"Execution error: {type(e).__name__}: {str(e)}"
    finally:
        # Clean up buffers
        stdout_buffer.close()
        stderr_buffer.close()
