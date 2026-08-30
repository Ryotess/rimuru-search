# src/orchestrator/exceptions.py
class OrchestratorException(Exception):
    """Base exception for orchestrator errors."""


class EmbeddingParseException(OrchestratorException):
    """Raised when the embedding response cannot be parsed into a vector."""
