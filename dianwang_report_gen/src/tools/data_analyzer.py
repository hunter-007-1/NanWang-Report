"""
Data Analyzer Tool for analyzing structured data files.

This tool provides statistical analysis capabilities for JSON, JSONL, CSV, and Excel files.
"""

from pathlib import Path
from typing import Union
from langchain.tools import tool
import json
import pandas as pd
import numpy as np


@tool(
    "data_analyzer",
    description=(
        "Perform statistical analysis on structured data files. "
        "Supports JSON, JSONL, CSV, and Excel formats. "
        "Analysis types: 'summary' (descriptive statistics), "
        "'correlation' (correlation matrix), 'distribution' (distribution stats), "
        "'all' (all analyses). "
        "Example: data_analyzer(path='data.json', analysis='summary')"
    ),
)
def data_analyzer(path: Union[str, Path], analysis: str = "summary") -> str:
    """
    Perform statistical analysis on a structured data file.

    Args:
        path: Path to the data file (JSON, JSONL, CSV, Excel)
        analysis: Type of analysis - 'summary', 'correlation', 'distribution', 'all'

    Returns:
        Analysis results as a formatted string
    """
    try:
        file_path = Path(path)

        # Validate file exists
        if not file_path.exists():
            return f"Error: File not found: {file_path}"

        # Load data based on file extension
        suffix = file_path.suffix.lower()

        if suffix == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            df = pd.DataFrame(data) if isinstance(data, list) else pd.DataFrame([data])

        elif suffix == ".jsonl":
            data = []
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    data.append(json.loads(line.strip()))
            df = pd.DataFrame(data)

        elif suffix == ".csv":
            df = pd.read_csv(file_path)

        elif suffix in [".xlsx", ".xls"]:
            df = pd.read_excel(file_path)

        else:
            return (
                f"Unsupported file format: {suffix}. Supported: JSON, JSONL, CSV, Excel"
            )

        # Perform analysis based on type
        result_parts = []

        if analysis in ["summary", "all"]:
            result_parts.append("=== Summary Statistics ===")
            result_parts.append(df.describe().to_string())
            result_parts.append("")

        if analysis in ["correlation", "all"]:
            numeric_df = df.select_dtypes(include=[np.number])
            if len(numeric_df.columns) > 1:
                result_parts.append("=== Correlation Matrix ===")
                result_parts.append(numeric_df.corr().to_string())
                result_parts.append("")
            else:
                result_parts.append("=== Correlation Matrix ===")
                result_parts.append(
                    "Not enough numeric columns for correlation analysis"
                )
                result_parts.append("")

        if analysis in ["distribution", "all"]:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                result_parts.append("=== Distribution Analysis ===")
                for col in numeric_cols:
                    result_parts.append(f"\n{col}:")
                    result_parts.append(f"  Mean: {df[col].mean():.4f}")
                    result_parts.append(f"  Median: {df[col].median():.4f}")
                    result_parts.append(f"  Std Dev: {df[col].std():.4f}")
                    result_parts.append(f"  Min: {df[col].min():.4f}")
                    result_parts.append(f"  Max: {df[col].max():.4f}")
                    result_parts.append(f"  Skewness: {df[col].skew():.4f}")
                    result_parts.append(f"  Kurtosis: {df[col].kurtosis():.4f}")
                result_parts.append("")

        # Add basic info
        result_parts.append("=== Dataset Info ===")
        result_parts.append(f"Shape: {df.shape[0]} rows x {df.shape[1]} columns")
        result_parts.append(f"Columns: {', '.join(df.columns.tolist())}")
        result_parts.append(
            f"Memory usage: {df.memory_usage(deep=True).sum() / 1024:.2f} KB"
        )

        return "\n".join(result_parts)

    except Exception as e:
        return f"Analysis error: {type(e).__name__}: {str(e)}"
