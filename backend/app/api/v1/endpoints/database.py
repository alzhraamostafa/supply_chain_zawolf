
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db


# Group database-related endpoints under one router.
router = APIRouter(prefix="/database", tags=["Database"])


# Read basic database information without modifying any records.
@router.get("/info")
def database_info(db: Annotated[Session, Depends(get_db)]):
    result = db.execute(
        text("""
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
        """)
    )

    table_count = result.scalar_one()

    return {
        "status": "connected",
        "table_count": table_count,
    }
