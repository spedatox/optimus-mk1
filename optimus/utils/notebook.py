"""
utils/notebook.py — partial port of src/utils/notebook.ts.

Only parseCellId is needed so far (NotebookEditTool). The rest of notebook.ts
— readNotebook, mapNotebookCellsToToolResult, processCell/processOutput, the
cell-to-tool-result block mappers — is the notebook reader used by
FileReadTool's .ipynb path, which is still RE-ENTRY (it currently raises a
"not yet supported" error). Port those when the FileRead notebook reader lands.
"""
from __future__ import annotations

import re
from typing import Optional

_CELL_ID_RE = re.compile(r"^cell-(\d+)$")


def parse_cell_id(cell_id: str) -> Optional[int]:
    """
    Mirrors parseCellId(): interpret a "cell-N" identifier as a 0-indexed cell
    position. Returns None when the id is not a numeric cell-N form.
    """
    match = _CELL_ID_RE.match(cell_id)
    if not match:
        return None
    try:
        index = int(match.group(1), 10)
    except (TypeError, ValueError):
        return None
    return index
