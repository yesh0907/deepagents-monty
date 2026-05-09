from typing import Any

def read_csv(path: str) -> list[dict[str, Any]]:
    """Read a CSV file from the agent filesystem.

    Returns one dictionary per row. Transaction Amount values are floats;
    other transaction columns are strings.
    """
    ...
