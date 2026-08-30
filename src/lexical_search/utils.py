def normalize_query(query: str) -> str:
    """
    Strip whitespace and coerce None to empty string to make validation downstream simpler.
    """
    return (query or "").strip()
