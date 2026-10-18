"""Application configuration loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Singleton configuration. All money values in minor units (KES cents)."""

    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "google")
    MODEL_NAME: str = os.getenv("MODEL_NAME", "gemini-3.8-flash")

    CAP_PER_TXN: int = int(os.getenv("CAP_PER_TXN", "2500000"))
    CAP_DAILY: int = int(os.getenv("CAP_DAILY", "5000000"))
    SAFETY_BUFFER_MINOR: int = int(os.getenv("SAFETY_BUFFER_MINOR", "500000"))
    BUFFER_DAYS_OF_OUTFLOW: int = int(os.getenv("BUFFER_DAYS_OF_OUTFLOW", "3"))

    SYNTHETIC_DATA_SEED: int = int(os.getenv("SYNTHETIC_DATA_SEED", "42"))
    SANDBOX_ONLY: bool = os.getenv("SANDBOX_ONLY", "true").lower() == "true"

    LLM_CACHE_DIR: str = os.getenv("LLM_CACHE_DIR", ".llm_cache")

    DB_PATH: str = os.getenv("DUKA_DB_PATH", "data/duka.db")

    @classmethod
    def caps_minor(cls) -> dict:
        return {"per_txn": cls.CAP_PER_TXN, "daily": cls.CAP_DAILY}


config = Config()
