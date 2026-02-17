"""Chart registry mapping chart names to their Pydantic value models.

Add new chart schemas here to make them available to the helm-schema CLI tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel


CHART_REGISTRY: dict[str, type[BaseModel]] = {
}
"""
Registry of Helm charts with Pydantic schema definitions.

To add a new chart:
1. Create a new package under rita/charts/<chart_name>/
2. Define the values schema in values.py using Pydantic BaseModel
3. Import the model here and add it to the registry

Example:
    from rita.charts.my_chart import MyChartValues

    CHART_REGISTRY = {
        ...
        "my-chart": MyChartValues,
    }
"""


def get_chart_model(chart_name: str) -> type[BaseModel] | None:
    """Get the Pydantic model for a chart by name.

    Args:
        chart_name: The name of the chart directory (e.g., "patient-app-stack")

    Returns:
        The Pydantic model class, or None if not found.
    """
    return CHART_REGISTRY.get(chart_name)


def list_registered_charts() -> list[str]:
    """List all chart names that have schema definitions.

    Returns:
        Sorted list of chart names.
    """
    return sorted(CHART_REGISTRY.keys())
