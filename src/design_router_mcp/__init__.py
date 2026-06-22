"""Design Router GPT-5.5 MCP packet compiler for frontend design routing."""

from .schemas import DesignContextRequest, RenderedPacket, RouteResolution
from .router import DesignRouter
from .renderer import build_context_packet
from .lazy_loader import load_repository_packs
from .service import resolve_design_packet

__all__ = [
    "DesignContextRequest",
    "RenderedPacket",
    "RouteResolution",
    "DesignRouter",
    "build_context_packet",
    "load_repository_packs",
    "resolve_design_packet",
]

__version__ = "0.2.1"
