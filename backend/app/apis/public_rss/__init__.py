from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
import asyncpg
import databutton as db
from datetime import datetime

router = APIRouter(prefix="/public/rss", tags=["Public RSS"])

class RSSSourceResponse(BaseModel):
    id: int
    name: str
    url: str
    description: Optional[str]
    credibility_score: int
    is_active: bool
    last_fetch_at: Optional[datetime]
    last_fetch_status: str
    last_error_message: Optional[str]
    fetch_count: int
    success_count: int
    created_at: datetime
    updated_at: datetime

# Database helper functions
async def get_db_connection():
    """Get database connection"""
    return await asyncpg.connect(db.secrets.get("DATABASE_URL_DEV"))

@router.get("/sources", response_model=List[RSSSourceResponse])
async def get_public_sources(
    active_only: bool = Query(True, description="Return only active sources"),
    min_credibility: int = Query(0, ge=0, le=100, description="Minimum credibility score"),
    order_by: str = Query("name", description="Order by: name, credibility_score, created_at, last_fetch_at")
) -> List[RSSSourceResponse]:
    """Get all RSS sources - COMPLETELY PUBLIC ENDPOINT"""
    
    conn = await get_db_connection()
    try:
        # Build query with filters
        where_conditions = []
        if active_only:
            where_conditions.append("is_active = true")
        if min_credibility > 0:
            where_conditions.append(f"credibility_score >= {min_credibility}")
        
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)
        
        # Validate order_by parameter
        valid_order_fields = ["name", "credibility_score", "created_at", "last_fetch_at"]
        if order_by not in valid_order_fields:
            order_by = "name"
        
        # Add DESC for credibility and date fields
        if order_by in ["credibility_score", "created_at", "last_fetch_at"]:
            order_by += " DESC"
        
        query = f"""
            SELECT id, name, url, description, credibility_score, is_active,
                   last_fetch_at, last_fetch_status, last_error_message,
                   fetch_count, success_count, created_at, updated_at
            FROM rss_sources
            {where_clause}
            ORDER BY {order_by}
        """
        
        print(f"Executing query: {query}")  # Debug log
        rows = await conn.fetch(query)
        print(f"Found {len(rows)} sources")  # Debug log
        
        return [RSSSourceResponse(**dict(row)) for row in rows]
        
    except Exception as e:
        print(f"Database error: {str(e)}")  # Debug log
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        await conn.close()
