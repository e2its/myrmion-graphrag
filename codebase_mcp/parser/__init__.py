"""Parsers de código: registro pluggable por extensión."""

from .base import (
    ParseResult,
    get_parser_for_path,
    module_name_from_path,
    supported_extensions,
)

__all__ = [
    "ParseResult",
    "get_parser_for_path",
    "module_name_from_path",
    "supported_extensions",
]
