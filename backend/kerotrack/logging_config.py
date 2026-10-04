"""Root logging setup so kerotrack.* INFO logs reach stderr under uvicorn."""

from __future__ import annotations

import logging
import sys

_HANDLER_NAME = "kerotrack-root"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str) -> None:
    lvl = logging.getLevelName(str(level).upper())
    if not isinstance(lvl, int):
        lvl = logging.INFO
    root = logging.getLogger()
    root.setLevel(lvl)
    for h in root.handlers:
        if getattr(h, "name", None) == _HANDLER_NAME:
            h.setLevel(lvl)
            return
    handler = logging.StreamHandler(sys.stderr)
    handler.name = _HANDLER_NAME
    handler.setLevel(lvl)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
