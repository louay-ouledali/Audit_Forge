"""Parser registry — maps config format IDs to parser classes."""

from __future__ import annotations

from backend.core.config_audit.parsers.base import BaseConfigParser, FallbackConfigParser


def get_parser(format_id: str) -> BaseConfigParser:
    """Return the appropriate parser for *format_id*."""
    # Lazy imports to avoid heavy dependencies at module import time
    _PARSERS: dict[str, type[BaseConfigParser]] = {}

    try:
        from backend.core.config_audit.parsers.ios_parser import IOSConfigParser
        _PARSERS["ios"] = IOSConfigParser
    except ImportError:
        pass

    try:
        from backend.core.config_audit.parsers.fortios_parser import FortiOSConfigParser
        _PARSERS["fortios"] = FortiOSConfigParser
    except ImportError:
        pass

    try:
        from backend.core.config_audit.parsers.panos_parser import PANOSConfigParser
        _PARSERS["panos_xml"] = PANOSConfigParser
    except ImportError:
        pass

    try:
        from backend.core.config_audit.parsers.junos_parser import JunOSConfigParser
        _PARSERS["junos"] = JunOSConfigParser
    except ImportError:
        pass

    try:
        from backend.core.config_audit.parsers.checkpoint_parser import CheckPointConfigParser
        _PARSERS["checkpoint"] = CheckPointConfigParser
    except ImportError:
        pass

    try:
        from backend.core.config_audit.parsers.pfsense_parser import PfSenseConfigParser
        _PARSERS["pfsense_xml"] = PfSenseConfigParser
    except ImportError:
        pass

    cls = _PARSERS.get(format_id)
    if cls is not None:
        return cls()
    return FallbackConfigParser()
