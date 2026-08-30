import asyncio

from src.logging_config import shutdown_logging
from src.seeding.service.seeder import seed

if __name__ == "__main__":
    try:
        asyncio.run(seed())
    finally:
        shutdown_logging()
