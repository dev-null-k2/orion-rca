"""Promotion windows."""
from datetime import datetime


def load_promotion(row: dict) -> dict:
    # Marketing enters dates as US Eastern wall-clock time.
    return {
        "code": row["code"],
        "starts_at": datetime.fromisoformat(row["starts_at"]),
        "ends_at": datetime.fromisoformat(row["ends_at"]),
    }


def is_active(promo: dict, now_utc: datetime) -> bool:
    return promo["starts_at"] <= now_utc.replace(tzinfo=None) <= promo["ends_at"]
