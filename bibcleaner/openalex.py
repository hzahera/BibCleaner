"""Backward-compatible OpenAlex client export.

The concrete implementation lives in providers.openalex and now follows the
shared provider abstraction.
"""

from providers.openalex import OpenAlexClient

__all__ = ["OpenAlexClient"]
