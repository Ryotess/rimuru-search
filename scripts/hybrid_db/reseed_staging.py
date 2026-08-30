import asyncio

from src.logging_config import shutdown_logging
from src.seeding.service.reseed import reseed

if __name__ == "__main__":
    try:
        asyncio.run(reseed())
    finally:
        shutdown_logging()
