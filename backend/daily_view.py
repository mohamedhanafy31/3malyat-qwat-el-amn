"""Authoritative combined view returned after daily mutations.

The individual board and duty endpoints remain available for compatibility,
but a successful mutation can now update the whole daily screen from one
response instead of issuing several follow-up reads.
"""

from . import confirm, day_status
from .board import build_board
from .store import revision


def _rest_state(data, day):
    leaves = [
        {
            "id": leave.get("id"),
            "person_id": leave.get("person_id"),
            "type": leave.get("type"),
            "start": leave.get("start"),
            "end": leave.get("end"),
            "return_date": leave.get("return_date"),
        }
        for leave in (data.get("leaves") or [])
        if (leave.get("start") or "") <= day <= (leave.get("end") or "")
    ]
    return {"count": len(leaves), "leaves": leaves}


def build(data, day):
    """Build the authoritative board/status/confirmation/revision payload."""
    return {
        "board": build_board(data, day),
        "day_status": day_status.status_of(data, day),
        "rest_state": _rest_state(data, day),
        "confirmation": confirm.state_of(data, day),
        "revision": revision(data, [day]),
    }
