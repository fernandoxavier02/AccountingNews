from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional
import asyncpg
import databutton as db
from datetime import datetime

router = APIRouter(prefix="/rss/sources", tags=["RSS Sources"])

# Pydantic Models
class RSSSourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Display name for the RSS source")
    url: HttpUrl = Field(..., description="RSS feed URL")
    description: Optional[str] = Field(None, max_length=500, description="Description of the RSS source")
    credibility_score: int = Field(70, ge=0, le=100, description="Source credibility score (0-100)")
    is_active: bool = Field(True, description="Whether the source is active")

class RSSSourceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    url: Optional[HttpUrl] = None
    description: Optional[str] = Field(None, max_length=500)
    credibility_score: Optional[int] = Field(None, ge=0, le=100)
    is_active: Optional[bool] = None

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
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.fetch_count == 0:
            return 0.0
        return (self.success_count / self.fetch_count) * 100

class RSSSourceStats(BaseModel):
    total_sources: int
    active_sources: int
    inactive_sources: int
    high_credibility_sources: int  # credibility >= 80
    sources_with_errors: int
    avg_credibility_score: float
    avg_success_rate: float

# Database helper functions
async def get_db_connection():
    """Get database connection"""
    return await asyncpg.connect(db.secrets.get("DATABASE_URL_DEV"))

@router.get("/", response_model=List[RSSSourceResponse])
async def get_all_sources(
    active_only: bool = Query(False, description="Return only active sources"),
    min_credibility: int = Query(0, ge=0, le=100, description="Minimum credibility score"),
    order_by: str = Query("name", description="Order by: name, credibility_score, created_at, last_fetch_at")
) -> List[RSSSourceResponse]:
    """Get all RSS sources with optional filtering (public endpoint)"""
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
        rows = await conn.fetch(query)
        return [RSSSourceResponse(**dict(row)) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        await conn.close()

@router.get("/stats", response_model=RSSSourceStats)
async def get_source_stats() -> RSSSourceStats:
    """Get RSS source statistics (public endpoint)"""
    conn = await get_db_connection()
    try:
        # Get various source statistics
        stats_query = """
            SELECT 
                COUNT(*) as total_sources,
                COUNT(CASE WHEN is_active = true THEN 1 END) as active_sources,
                COUNT(CASE WHEN is_active = false THEN 1 END) as inactive_sources,
                COUNT(CASE WHEN credibility_score >= 80 THEN 1 END) as high_credibility_sources,
                COUNT(CASE WHEN last_fetch_status = 'error' THEN 1 END) as sources_with_errors,
                AVG(credibility_score) as avg_credibility_score,
                AVG(CASE 
                    WHEN fetch_count > 0 THEN (success_count::float / fetch_count::float) * 100 
                    ELSE 0 
                END) as avg_success_rate
            FROM rss_sources
        """
        
        stats_row = await conn.fetchrow(stats_query)
        
        return RSSSourceStats(
            total_sources=stats_row['total_sources'] or 0,
            active_sources=stats_row['active_sources'] or 0,
            inactive_sources=stats_row['inactive_sources'] or 0,
            high_credibility_sources=stats_row['high_credibility_sources'] or 0,
            sources_with_errors=stats_row['sources_with_errors'] or 0,
            avg_credibility_score=float(stats_row['avg_credibility_score']) if stats_row['avg_credibility_score'] else 0.0,
            avg_success_rate=float(stats_row['avg_success_rate']) if stats_row['avg_success_rate'] else 0.0
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        await conn.close()
