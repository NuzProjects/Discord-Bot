from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path("data")
APPEALS_FILE = DATA_DIR / "appeals.json"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_store() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not APPEALS_FILE.exists():
        APPEALS_FILE.write_text(json.dumps({"appeals": {}}, indent=2), encoding="utf-8")


def load_appeals() -> dict[str, Any]:
    _ensure_store()
    try:
        return json.loads(APPEALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"appeals": {}}


def save_appeals(data: dict[str, Any]) -> None:
    _ensure_store()
    APPEALS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_appeal(appeal_id: str) -> dict[str, Any] | None:
    data = load_appeals()
    return (data.get("appeals") or {}).get(str(appeal_id))


def create_appeal_record(
    *,
    case_id: int,
    guild_id: int,
    guild_name: str,
    user_id: int,
    user_name: str,
    action: str,
    reason: str,
    moderator_id: int,
) -> dict[str, Any]:
    data = load_appeals()
    appeals = data.setdefault("appeals", {})

    appeal_id = ""
    while not appeal_id or appeal_id in appeals:
        appeal_id = secrets.token_urlsafe(9).replace("-", "").replace("_", "")

    record = {
        "id": appeal_id,
        "case_id": int(case_id),
        "guild_id": str(guild_id),
        "guild_name": guild_name,
        "user_id": str(user_id),
        "user_name": user_name,
        "action": action,
        "reason": reason,
        "moderator_id": str(moderator_id),
        "created_at": utcnow_iso(),
        "status": "open",
        "submitted_at": None,
        "appeal_text": "",
    }
    appeals[appeal_id] = record
    save_appeals(data)
    return record


def submit_appeal(appeal_id: str, appeal_text: str) -> dict[str, Any] | None:
    data = load_appeals()
    appeals = data.setdefault("appeals", {})
    record = appeals.get(str(appeal_id))
    if not record:
        return None

    record["appeal_text"] = appeal_text
    record["submitted_at"] = utcnow_iso()
    record["status"] = "submitted"
    save_appeals(data)
    return record

