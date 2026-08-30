from src.config import app_settings

ROWS_PER_CHUNK = app_settings.seed_rows_per_chunk
EMBED_BATCH_SIZE = app_settings.seed_embed_batch_size
DB_BATCH_SIZE = app_settings.seed_db_batch_size
MAX_EMBED_CONCURRENCY = app_settings.seed_max_embed_concurrency
