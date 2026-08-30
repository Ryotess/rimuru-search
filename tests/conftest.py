import os
import sys
from pathlib import Path

# Provide minimal settings so BaseSettings objects that are constructed at import
# time do not fail validation during tests.
os.environ.setdefault("GLOBAL_DATABASE_URL", "postgresql://example.com/db")
os.environ.setdefault("EMBED_HOSTED_VLLM_API_BASE", "http://localhost:5678/v1")
os.environ.setdefault("EMBEDDING_MODEL_ID", "example/embedding-1024")
os.environ.setdefault("RERANKER_HOSTED_VLLM_API_BASE", "http://localhost:5679")
os.environ.setdefault("RERANKER_MODEL_ID", "example/reranker")
os.environ.setdefault("SOURCE_API_BASE_URL", "http://localhost:3000")

# Ensure the src package is importable regardless of PYTHONPATH settings in the runner.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
