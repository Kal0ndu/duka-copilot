"""Application configuration loaded from environment variables."""
import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Singleton configuration. All money values in minor units (KES cents)."""

    LLM_API_KEY: str = os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY", "")  # either name works
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


# ---- Tool wrapper function for knowledge search ----

def search_knowledge(args, business_id: Optional[int] = None,
                    db_path: Optional[str] = None) -> dict:
    """Search the knowledge base for relevant information.
    
    Args:
        args: SearchKnowledgeArgs with query string
        business_id: Active business ID (not used for KB search)
        db_path: Database path
    
    Returns:
        dict with top chunks with ids and scores
    """
    from typing import Optional
    
    try:
        query = args.query or ""
        if not query:
            return {"error": "query required"}
        
        # Simple keyword-based search in knowledge base
        # In production, this would use vector embeddings
        # For now, return a basic response with relevant tips
        
        knowledge_base = {
            "cash_flow": {
                "id": "kb_001",
                "title": "Managing Cash Flow",
                "content": "Track daily inflows and outflows. Maintain a safety buffer of at least 3 days of expenses. Monitor weekly patterns to forecast shortfalls.",
                "relevance": 0.9 if any(w in query.lower() for w in ["cash", "flow", "balance"]) else 0.3,
            },
            "inventory": {
                "id": "kb_002",
                "title": "Inventory Management",
                "content": "Stock purchases should not exceed 40% of monthly revenue. Track supplier payments to negotiate better terms.",
                "relevance": 0.9 if any(w in query.lower() for w in ["stock", "inventory", "supplier"]) else 0.3,
            },
            "loans": {
                "id": "kb_003",
                "title": "Understanding Digital Loans",
                "content": "Digital lenders offer quick disbursals. Compare EAR, TCC, and repayment terms. Ensure monthly repayment does not exceed 15% of expected profit.",
                "relevance": 0.9 if any(w in query.lower() for w in ["loan", "financing", "borrow"]) else 0.3,
            },
            "personal_spending": {
                "id": "kb_004",
                "title": "Personal Spending Control",
                "content": "Keep personal withdrawals below 20% of net profit. Use business funds only for business purposes to improve financial visibility.",
                "relevance": 0.9 if any(w in query.lower() for w in ["personal", "withdraw", "spending"]) else 0.3,
            },
            "tax": {
                "id": "kb_005",
                "title": "Tax and Compliance",
                "content": "Register with KRA if revenue exceeds 5M KES annually. Maintain records of all expenses. Pay taxes on time to avoid penalties.",
                "relevance": 0.9 if any(w in query.lower() for w in ["tax", "compliance", "kra"]) else 0.3,
            },
        }
        
        # Filter by relevance
        results = [
            {
                "id": kb["id"],
                "title": kb["title"],
                "content": kb["content"],
                "score": kb["relevance"],
            }
            for kb in knowledge_base.values()
            if kb["relevance"] > 0.5
        ]
        
        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        
        return {
            "query": query,
            "results": results,
            "count": len(results),
        }
    
    except Exception as e:
        return {"error": f"Knowledge search failed: {e}"}
