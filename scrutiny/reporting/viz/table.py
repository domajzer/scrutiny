
from typing import List, Any
from dominate import tags
import uuid

from scrutiny.htmlutils import show_hide_div

def render_table_block(headers: List[str], rows: List[List[Any]]):
    """
    Render a generic table block.
    headers: list of column titles
    rows: list of row values (already formatted for display)
    Returns a dominate node (<div> containing a table).
    """
    div_id = f"tbl-{uuid.uuid4().hex[:8]}"
    container = tags.div(_class="table-container", id=div_id)
    # Show/Hide controls expect the *id string*, not the DOM node
    show_hide_div(div_id)

    with container:
        table = tags.table(_class="report-table")
        with table:
            thead = tags.thead()
            with thead:
                tr = tags.tr()
                for h in headers:
                    tags.th(str(h))
            tbody = tags.tbody()
            with tbody:
                for r in rows or []:
                    tr = tags.tr()
                    # r can be a list/tuple or a single value
                    cells = r if isinstance(r, (list, tuple)) else [r]
                    for c in cells:
                        # c can be a dominate tag or string/number
                        if hasattr(c, '__html__') or hasattr(c, 'render'):
                            tags.td(c)
                        else:
                            tags.td(str(c))
    return container
