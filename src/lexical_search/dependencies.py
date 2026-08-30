"""
Shared dependencies for lexical search routes.
Currently re-exports the database session dependency for convenience.
"""

from src.database import get_session

__all__ = ["get_session"]
