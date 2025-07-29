from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import asyncpg
import databutton as db
from datetime import datetime
from app.auth import AuthorizedUser
from app.libs.access_middleware import verify_email_authorization
import json

router = APIRouter()

class BookmarkRequest(BaseModel):
    """Request to create or update a bookmark"""
    feed_item_id: int = Field(..., description="RSS feed item ID to bookmark")
    notes: Optional[str] = Field(None, max_length=1000, description="User notes about the bookmark")
    tags: Optional[List[str]] = Field(None, description="User-defined tags for organization")
    is_archived: Optional[bool] = Field(False, description="Archive flag for later use")

class BookmarkResponse(BaseModel):
    """Bookmark response with feed item details"""
    id: int
    feed_item_id: int
    notes: Optional[str]
    tags: List[str]
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    # Feed item details
    title: str
    description: Optional[str]
    link: str
    pub_date: Optional[datetime]
    priority: str
    relevance_score: int
    category: str
    source_name: Optional[str]

class BookmarkListResponse(BaseModel):
    """Response for listing bookmarks"""
    bookmarks: List[BookmarkResponse]
    total_count: int
    page: int
    per_page: int
    total_pages: int

class BookmarkStatsResponse(BaseModel):
    """Bookmark statistics"""
    total_bookmarks: int
    archived_bookmarks: int
    active_bookmarks: int
    categories_distribution: List[Dict[str, Any]]
    tags_distribution: List[Dict[str, Any]]
    recent_bookmarks_count: int

class ExportRequest(BaseModel):
    """Export request for bookmarks or search results"""
    bookmark_ids: Optional[List[int]] = Field(None, description="Specific bookmark IDs to export")
    search_query: Optional[str] = Field(None, description="Export search results instead")
    format: str = Field('json', description="Export format: json, csv, txt")
    include_archived: bool = Field(False, description="Include archived bookmarks")
    include_notes: bool = Field(True, description="Include user notes in export")
    include_tags: bool = Field(True, description="Include tags in export")

class ExportResponse(BaseModel):
    """Export response"""
    content: str
    filename: str
    content_type: str
    items_count: int

async def get_db_connection():
    """Get database connection"""
    return await asyncpg.connect(db.secrets.get("DATABASE_URL_DEV"))

@router.post("/bookmarks")
async def create_bookmark(
    request: BookmarkRequest,
    user: AuthorizedUser = verify_email_authorization
) -> BookmarkResponse:
    """Create a new bookmark for the authenticated user"""
    try:
        conn = await get_db_connection()
        
        # Check if feed item exists
        feed_item = await conn.fetchrow("""
            SELECT fi.*, rs.name as source_name
            FROM rss_feed_items fi
            LEFT JOIN rss_sources rs ON fi.source_id = rs.id
            WHERE fi.id = $1
        """, request.feed_item_id)
        
        if not feed_item:
            raise HTTPException(status_code=404, detail="Feed item not found")
        
        # Create bookmark (ON CONFLICT UPDATE to handle duplicates)
        bookmark = await conn.fetchrow("""
            INSERT INTO user_bookmarks (user_id, feed_item_id, notes, tags, is_archived)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id, feed_item_id) 
            DO UPDATE SET 
                notes = EXCLUDED.notes,
                tags = EXCLUDED.tags,
                is_archived = EXCLUDED.is_archived,
                updated_at = NOW()
            RETURNING *
        """, user.sub, request.feed_item_id, request.notes, request.tags or [], request.is_archived)
        
        await conn.close()
        
        return BookmarkResponse(
            id=bookmark['id'],
            feed_item_id=bookmark['feed_item_id'],
            notes=bookmark['notes'],
            tags=list(bookmark['tags']) if bookmark['tags'] else [],
            is_archived=bookmark['is_archived'],
            created_at=bookmark['created_at'],
            updated_at=bookmark['updated_at'],
            title=feed_item['title'],
            description=feed_item['description'],
            link=feed_item['link'],
            pub_date=feed_item['pub_date'],
            priority=feed_item['priority'],
            relevance_score=feed_item['relevance_score'],
            category=feed_item['category'],
            source_name=feed_item['source_name']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Create bookmark error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create bookmark: {str(e)}")

@router.get("/bookmarks")
async def list_bookmarks(
    tag: Optional[str] = Query(None, description="Filter by tag"),
    search: Optional[str] = Query(None, description="Search in titles and content"),
    limit: int = Query(50, ge=1, le=100, description="Number of bookmarks to return"),
    offset: int = Query(0, ge=0, description="Number of bookmarks to skip"),
    user: AuthorizedUser = verify_email_authorization
) -> BookmarkListResponse:
    """List user's bookmarks with filtering and pagination"""
    try:
        conn = await get_db_connection()
        
        # Build query conditions
        conditions = ["ub.user_id = $1"]
        params = [user.sub]
        param_index = 2
        
        if tag:
            conditions.append(f"${param_index} = ANY(ub.tags)")
            params.append(tag)
            param_index += 1
        
        if search:
            conditions.append(f"fi.title ILIKE ${param_index} OR fi.content ILIKE ${param_index}")
            params.append(f"%{search}%")
            param_index += 1
        
        where_clause = " AND ".join(conditions)
        
        # Get total count
        total_count = await conn.fetchval(f"""
            SELECT COUNT(*)
            FROM user_bookmarks ub
            LEFT JOIN rss_feed_items fi ON ub.feed_item_id = fi.id
            WHERE {where_clause}
        """, *params)
        
        # Get bookmarks with pagination
        bookmarks = await conn.fetch(f"""
            SELECT 
                ub.id, ub.feed_item_id, ub.notes, ub.tags, ub.is_archived,
                ub.created_at, ub.updated_at,
                fi.title, fi.description, fi.link, fi.pub_date, fi.priority,
                fi.relevance_score, fi.category,
                rs.name as source_name
            FROM user_bookmarks ub
            LEFT JOIN rss_feed_items fi ON ub.feed_item_id = fi.id
            LEFT JOIN rss_sources rs ON fi.source_id = rs.id
            WHERE {where_clause}
            LIMIT ${param_index} OFFSET ${param_index + 1}
        """, *params, limit, offset)
        
        await conn.close()
        
        # Format response
        bookmark_list = []
        for row in bookmarks:
            bookmark_list.append(BookmarkResponse(
                id=row['id'],
                feed_item_id=row['feed_item_id'],
                notes=row['notes'],
                tags=list(row['tags']) if row['tags'] else [],
                is_archived=row['is_archived'],
                created_at=row['created_at'],
                updated_at=row['updated_at'],
                title=row['title'],
                description=row['description'],
                link=row['link'],
                pub_date=row['pub_date'],
                priority=row['priority'],
                relevance_score=row['relevance_score'],
                category=row['category'],
                source_name=row['source_name']
            ))
        
        total_pages = (total_count + limit - 1) // limit
        
        return BookmarkListResponse(
            bookmarks=bookmark_list,
            total_count=total_count,
            page=(offset // limit) + 1,
            per_page=limit,
            total_pages=total_pages
        )
        
    except Exception as e:
        print(f"List bookmarks error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list bookmarks: {str(e)}")

@router.get("/bookmarks/{bookmark_id}")
async def get_bookmark(
    bookmark_id: int,
    user: AuthorizedUser = verify_email_authorization
) -> BookmarkResponse:
    """Get a specific bookmark by ID"""
    try:
        conn = await get_db_connection()
        
        bookmark = await conn.fetchrow("""
            SELECT 
                ub.id, ub.feed_item_id, ub.notes, ub.tags, ub.is_archived,
                ub.created_at, ub.updated_at,
                fi.title, fi.description, fi.link, fi.pub_date, fi.priority,
                fi.relevance_score, fi.category,
                rs.name as source_name
            FROM user_bookmarks ub
            LEFT JOIN rss_feed_items fi ON ub.feed_item_id = fi.id
            LEFT JOIN rss_sources rs ON fi.source_id = rs.id
            WHERE ub.id = $1 AND ub.user_id = $2
        """, bookmark_id, user.sub)
        
        await conn.close()
        
        if not bookmark:
            raise HTTPException(status_code=404, detail="Bookmark not found")
        
        return BookmarkResponse(
            id=bookmark['id'],
            feed_item_id=bookmark['feed_item_id'],
            notes=bookmark['notes'],
            tags=list(bookmark['tags']) if bookmark['tags'] else [],
            is_archived=bookmark['is_archived'],
            created_at=bookmark['created_at'],
            updated_at=bookmark['updated_at'],
            title=bookmark['title'],
            description=bookmark['description'],
            link=bookmark['link'],
            pub_date=bookmark['pub_date'],
            priority=bookmark['priority'],
            relevance_score=bookmark['relevance_score'],
            category=bookmark['category'],
            source_name=bookmark['source_name']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Get bookmark error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get bookmark: {str(e)}")

@router.put("/bookmarks/{bookmark_id}")
async def update_bookmark(
    bookmark_id: int,
    request: BookmarkRequest,
    user: AuthorizedUser = verify_email_authorization
) -> BookmarkResponse:
    """Update an existing bookmark"""
    try:
        conn = await get_db_connection()
        
        # Update bookmark
        updated_bookmark = await conn.fetchrow("""
            UPDATE user_bookmarks 
            SET notes = $3, tags = $4, is_archived = $5, updated_at = NOW()
            WHERE id = $1 AND user_id = $2
            RETURNING *
        """, bookmark_id, user.sub, request.notes, request.tags or [], request.is_archived)
        
        if not updated_bookmark:
            raise HTTPException(status_code=404, detail="Bookmark not found")
        
        # Get feed item details
        feed_item = await conn.fetchrow("""
            SELECT fi.*, rs.name as source_name
            FROM rss_feed_items fi
            LEFT JOIN rss_sources rs ON fi.source_id = rs.id
            WHERE fi.id = $1
        """, updated_bookmark['feed_item_id'])
        
        await conn.close()
        
        return BookmarkResponse(
            id=updated_bookmark['id'],
            feed_item_id=updated_bookmark['feed_item_id'],
            notes=updated_bookmark['notes'],
            tags=list(updated_bookmark['tags']) if updated_bookmark['tags'] else [],
            is_archived=updated_bookmark['is_archived'],
            created_at=updated_bookmark['created_at'],
            updated_at=updated_bookmark['updated_at'],
            title=feed_item['title'],
            description=feed_item['description'],
            link=feed_item['link'],
            pub_date=feed_item['pub_date'],
            priority=feed_item['priority'],
            relevance_score=feed_item['relevance_score'],
            category=feed_item['category'],
            source_name=feed_item['source_name']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Update bookmark error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update bookmark: {str(e)}")

@router.delete("/bookmarks/{bookmark_id}")
async def delete_bookmark(
    bookmark_id: int,
    user: AuthorizedUser = verify_email_authorization
) -> dict:
    """Delete a bookmark"""
    try:
        conn = await get_db_connection()
        
        result = await conn.execute("""
            DELETE FROM user_bookmarks 
            WHERE id = $1 AND user_id = $2
        """, bookmark_id, user.sub)
        
        await conn.close()
        
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Bookmark not found")
        
        return {"message": "Bookmark deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Delete bookmark error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete bookmark: {str(e)}")

@router.get("/bookmarks/stats")
async def get_bookmark_stats(
    user: AuthorizedUser = verify_email_authorization
) -> BookmarkStatsResponse:
    """Get bookmark statistics for the user"""
    try:
        conn = await get_db_connection()
        
        # Get basic counts
        stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE is_archived = true) as archived,
                COUNT(*) FILTER (WHERE is_archived = false) as active,
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') as recent
            FROM user_bookmarks
            WHERE user_id = $1
        """, user.sub)
        
        # Get category distribution
        categories = await conn.fetch("""
            SELECT fi.category, COUNT(*) as count
            FROM user_bookmarks ub
            LEFT JOIN rss_feed_items fi ON ub.feed_item_id = fi.id
            WHERE ub.user_id = $1 AND ub.is_archived = false
            GROUP BY fi.category
            ORDER BY count DESC
        """, user.sub)
        
        # Get tags distribution
        tags = await conn.fetch("""
            SELECT unnest(tags) as tag, COUNT(*) as count
            FROM user_bookmarks
            WHERE user_id = $1 AND is_archived = false AND tags IS NOT NULL
            GROUP BY tag
            ORDER BY count DESC
            LIMIT 20
        """, user.sub)
        
        await conn.close()
        
        return BookmarkStatsResponse(
            total_bookmarks=stats['total'] or 0,
            archived_bookmarks=stats['archived'] or 0,
            active_bookmarks=stats['active'] or 0,
            recent_bookmarks_count=stats['recent'] or 0,
            categories_distribution=[
                {'category': row['category'], 'count': row['count']}
                for row in categories
            ],
            tags_distribution=[
                {'tag': row['tag'], 'count': row['count']}
                for row in tags
            ]
        )
        
    except Exception as e:
        print(f"Bookmark stats error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get bookmark stats: {str(e)}")

@router.post("/export")
async def export_content(
    request: ExportRequest,
    user: AuthorizedUser = verify_email_authorization
) -> ExportResponse:
    """Export bookmarks or search results in various formats"""
    try:
        conn = await get_db_connection()
        
        # Determine what to export
        if request.bookmark_ids:
            # Export specific bookmarks
            placeholders = ','.join(f'${i}' for i in range(2, len(request.bookmark_ids) + 2))
            query = f"""
                SELECT 
                    ub.notes, ub.tags, ub.created_at as bookmarked_at,
                    fi.title, fi.description, fi.content, fi.link, fi.pub_date,
                    fi.priority, fi.relevance_score, fi.category, fi.keywords,
                    rs.name as source_name
                FROM user_bookmarks ub
                LEFT JOIN rss_feed_items fi ON ub.feed_item_id = fi.id
                LEFT JOIN rss_sources rs ON fi.source_id = rs.id
                WHERE ub.user_id = $1 AND ub.id IN ({placeholders})
            """
            
            if not request.include_archived:
                query += " AND ub.is_archived = false"
            
            params = [user.sub] + request.bookmark_ids
            
        elif request.search_query:
            # Export search results (simplified for now)
            query = """
                SELECT 
                    fi.title, fi.description, fi.content, fi.link, fi.pub_date,
                    fi.priority, fi.relevance_score, fi.category, fi.keywords,
                    rs.name as source_name
                FROM rss_feed_items fi
                LEFT JOIN rss_sources rs ON fi.source_id = rs.id
                WHERE to_tsvector('portuguese', fi.title || ' ' || COALESCE(fi.description, '') || ' ' || COALESCE(fi.content, '')) 
                      @@ to_tsquery('portuguese', $2)
                ORDER BY ts_rank_cd(
                    to_tsvector('portuguese', fi.title || ' ' || COALESCE(fi.description, '') || ' ' || COALESCE(fi.content, '')),
                    to_tsquery('portuguese', $2)
                ) DESC
                LIMIT 100
            """
            params = [user.sub, request.search_query.replace(' ', ' & ')]
        else:
            # Export all bookmarks
            query = """
                SELECT 
                    ub.notes, ub.tags, ub.created_at as bookmarked_at,
                    fi.title, fi.description, fi.content, fi.link, fi.pub_date,
                    fi.priority, fi.relevance_score, fi.category, fi.keywords,
                    rs.name as source_name
                FROM user_bookmarks ub
                LEFT JOIN rss_feed_items fi ON ub.feed_item_id = fi.id
                LEFT JOIN rss_sources rs ON fi.source_id = rs.id
                WHERE ub.user_id = $1
            """
            
            if not request.include_archived:
                query += " AND ub.is_archived = false"
            
            params = [user.sub]
        
        rows = await conn.fetch(query, *params)
        await conn.close()
        
        # Format based on requested format
        if request.format == 'json':
            content = export_as_json(rows, request)
            content_type = 'application/json'
            filename = f'tributoflow_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        elif request.format == 'csv':
            content = export_as_csv(rows, request)
            content_type = 'text/csv'
            filename = f'tributoflow_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        elif request.format == 'txt':
            content = export_as_txt(rows, request)
            content_type = 'text/plain'
            filename = f'tributoflow_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
        else:
            raise HTTPException(status_code=400, detail="Unsupported export format")
        
        return ExportResponse(
            content=content,
            filename=filename,
            content_type=content_type,
            items_count=len(rows)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Export error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to export content: {str(e)}")

def export_as_json(rows, request: ExportRequest) -> str:
    """Export data as JSON"""
    data = []
    for row in rows:
        item = {
            'title': row['title'],
            'description': row['description'],
            'link': row['link'],
            'pub_date': row['pub_date'].isoformat() if row['pub_date'] else None,
            'source': row['source_name'],
            'category': row['category'],
            'priority': row['priority'],
            'relevance_score': row['relevance_score'],
            'keywords': list(row['keywords']) if row['keywords'] else []
        }
        
        # Add bookmark-specific fields if available
        if 'bookmarked_at' in row and row['bookmarked_at']:
            item['bookmarked_at'] = row['bookmarked_at'].isoformat()
            if request.include_notes and row['notes']:
                item['notes'] = row['notes']
            if request.include_tags and row['tags']:
                item['tags'] = list(row['tags'])
        
        data.append(item)
    
    return json.dumps({
        'export_info': {
            'exported_at': datetime.now().isoformat(),
            'items_count': len(data),
            'format': 'json'
        },
        'items': data
    }, indent=2, ensure_ascii=False)

def export_as_csv(rows, request: ExportRequest) -> str:
    """Export data as CSV"""
    import csv
    import io
    
    output = io.StringIO()
    fieldnames = ['title', 'description', 'link', 'pub_date', 'source', 'category', 'priority', 'relevance_score']
    
    # Add bookmark fields if applicable
    if any('bookmarked_at' in row and row['bookmarked_at'] for row in rows):
        fieldnames.append('bookmarked_at')
        if request.include_notes:
            fieldnames.append('notes')
        if request.include_tags:
            fieldnames.append('tags')
    
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    
    for row in rows:
        csv_row = {
            'title': row['title'],
            'description': row['description'] or '',
            'link': row['link'],
            'pub_date': row['pub_date'].isoformat() if row['pub_date'] else '',
            'source': row['source_name'] or '',
            'category': row['category'],
            'priority': row['priority'],
            'relevance_score': row['relevance_score']
        }
        
        if 'bookmarked_at' in row and row['bookmarked_at']:
            csv_row['bookmarked_at'] = row['bookmarked_at'].isoformat()
            if request.include_notes:
                csv_row['notes'] = row['notes'] or ''
            if request.include_tags:
                csv_row['tags'] = ', '.join(row['tags']) if row['tags'] else ''
        
        writer.writerow(csv_row)
    
    return output.getvalue()

def export_as_txt(rows, request: ExportRequest) -> str:
    """Export data as plain text"""
    content = []
    content.append(f"TributoFlow Export - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    content.append(f"Total items: {len(rows)}")
    content.append("=" * 80)
    content.append("")
    
    for i, row in enumerate(rows, 1):
        content.append(f"{i}. {row['title']}")
        content.append(f"   Source: {row['source_name'] or 'Unknown'}")
        content.append(f"   Category: {row['category']} | Priority: {row['priority']}")
        content.append(f"   Published: {row['pub_date'].strftime('%Y-%m-%d %H:%M') if row['pub_date'] else 'Unknown'}")
        content.append(f"   Link: {row['link']}")
        
        if row['description']:
            content.append(f"   Description: {row['description'][:200]}{'...' if len(row['description']) > 200 else ''}")
        
        if 'bookmarked_at' in row and row['bookmarked_at']:
            content.append(f"   Bookmarked: {row['bookmarked_at'].strftime('%Y-%m-%d %H:%M')}")
            if request.include_notes and row['notes']:
                content.append(f"   Notes: {row['notes']}")
            if request.include_tags and row['tags']:
                content.append(f"   Tags: {', '.join(row['tags'])}")
        
        content.append("")
        content.append("-" * 80)
        content.append("")
    
    return "\n".join(content)
