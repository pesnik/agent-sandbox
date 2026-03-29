"""Aggregate all MCP tool definitions and handlers from sub-modules."""

from .android import HANDLERS as _AH, IMAGE_TOOLS as _AI, TOOLS as _AT
from .browser import HANDLERS as _BH, IMAGE_TOOLS as _BI, TOOLS as _BT
from .google_messages import HANDLERS as _GH, TOOLS as _GT
from .outlook import HANDLERS as _OH, TOOLS as _OT
from .system import HANDLERS as _SH, TOOLS as _ST
from .whatsapp import HANDLERS as _WH, TOOLS as _WT

TOOLS = _ST + _BT + _OT + _GT + _AT + _WT

HANDLERS: dict = {**_SH, **_BH, **_OH, **_GH, **_AH, **_WH}

IMAGE_TOOLS: set[str] = _BI | _AI
