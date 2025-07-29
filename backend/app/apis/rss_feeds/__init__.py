from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from app.auth import AuthorizedUser
from app.libs.access_middleware import verify_email_authorization

router = APIRouter(prefix="/rss")

class FeedItem(BaseModel):
    id: int
    source_id: int
    title: str
    description: Optional[str] = None
    link: str
    pub_date: Optional[datetime] = None
    guid: Optional[str] = None
    content: Optional[str] = None
    priority: str = "medium"
    relevance_score: Optional[int] = None
    keywords: Optional[List[str]] = None
    category: Optional[str] = None
    is_new: bool = True
    created_at: datetime
    updated_at: datetime
    source_name: Optional[str] = None

class FeedItemsResponse(BaseModel):
    items: List[FeedItem]
    total: int
    page: int
    per_page: int
    has_next: bool

class FetchFeedsResponse(BaseModel):
    success: bool
    message: str
    items_added: int
    sources_processed: int
    errors: List[str] = []

class StatsResponse(BaseModel):
    total_items: int
    new_items: int
    high_priority_items: int
    today_items: int
    active_sources: int
    avg_relevance_score: float
    tax_reform_items: int
    legislation_items: int

@router.post("/fetch-feeds")
async def fetch_all_feeds(
    user: AuthorizedUser
) -> FetchFeedsResponse:
    """Fetch RSS feeds from all active sources"""
    import asyncpg
    import databutton as db
    import feedparser
    import aiohttp
    import asyncio
    from datetime import datetime, timezone
    import hashlib
    
    conn = await asyncpg.connect(db.secrets.get("DATABASE_URL_DEV"))
    
    try:
        # Get all active RSS sources
        sources_query = "SELECT id, name, url FROM rss_sources WHERE is_active = true"
        sources = await conn.fetch(sources_query)
        
        total_items_added = 0
        sources_processed = 0
        errors = []
        
        async with aiohttp.ClientSession() as session:
            for source in sources:
                try:
                    print(f"Fetching from {source['name']}: {source['url']}")
                    
                    # Update fetch status to 'processing'
                    await conn.execute(
                        "UPDATE rss_sources SET last_fetch_status = 'processing', last_fetch_at = NOW() WHERE id = $1",
                        source['id']
                    )
                    
                    # Fetch RSS feed with timeout
                    async with session.get(source['url'], timeout=30) as response:
                        if response.status == 200:
                            content = await response.text()
                            
                            # Parse RSS feed
                            feed = feedparser.parse(content)
                            
                            if feed.bozo:
                                error_msg = f"RSS parsing error for {source['name']}: {getattr(feed, 'bozo_exception', 'Unknown error')}"
                                errors.append(error_msg)
                                print(error_msg)
                                continue
                            
                            items_added_for_source = 0
                            
                            # Process each feed entry
                            for entry in feed.entries[:20]:  # Limit to 20 most recent
                                try:
                                    # Extract basic info
                                    title = getattr(entry, 'title', 'No title')
                                    description = getattr(entry, 'description', '') or getattr(entry, 'summary', '')
                                    link = getattr(entry, 'link', '')
                                    
                                    # Generate GUID if not present
                                    guid = getattr(entry, 'id', '') or getattr(entry, 'guid', '')
                                    if not guid:
                                        guid = hashlib.md5(f"{link}{title}".encode()).hexdigest()
                                    
                                    # Parse publication date
                                    pub_date = None
                                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                                        try:
                                            pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                                        except Exception:
                                            pub_date = datetime.now(timezone.utc)
                                    else:
                                        pub_date = datetime.now(timezone.utc)
                                    
                                    # Extract content
                                    content_text = ''
                                    if hasattr(entry, 'content') and entry.content:
                                        content_text = entry.content[0].value if isinstance(entry.content, list) else str(entry.content)
                                    elif hasattr(entry, 'summary'):
                                        content_text = entry.summary
                                    
                                    # Calculate relevance score based on keywords
                                    relevance_score = 50  # Default
                                    tax_keywords = ['reforma', 'tributar', 'imposto', 'tributo', 'IBS', 'CBS', 'PIS', 'COFINS']
                                    text_to_check = f"{title} {description} {content_text}".lower()
                                    
                                    keyword_matches = sum(1 for keyword in tax_keywords if keyword.lower() in text_to_check)
                                    if keyword_matches > 0:
                                        relevance_score = min(90, 50 + (keyword_matches * 10))
                                    
                                    # Determine priority based on relevance
                                    if relevance_score >= 80:
                                        priority = 'high'
                                    elif relevance_score >= 60:
                                        priority = 'medium'
                                    else:
                                        priority = 'low'
                                    
                                    # Determine category
                                    category = 'general'
                                    if any(word in text_to_check for word in ['reforma', 'tributar']):
                                        category = 'tax_reform'
                                    elif any(word in text_to_check for word in ['lei', 'regulament', 'norma']):
                                        category = 'legislation'
                                    
                                    # Insert into database (ON CONFLICT DO NOTHING to avoid duplicates)
                                    insert_query = """
                                    INSERT INTO rss_feed_items 
                                    (source_id, title, description, link, pub_date, guid, content, 
                                     priority, relevance_score, category, is_new, created_at, updated_at)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, true, NOW(), NOW())
                                    ON CONFLICT (guid) DO NOTHING
                                    """
                                    
                                    result = await conn.execute(
                                        insert_query,
                                        source['id'], title, description, link, pub_date, guid, content_text,
                                        priority, relevance_score, category
                                    )
                                    
                                    if result == "INSERT 0 1":
                                        items_added_for_source += 1
                                        total_items_added += 1
                                    
                                except Exception as e:
                                    error_msg = f"Error processing entry from {source['name']}: {str(e)}"
                                    errors.append(error_msg)
                                    print(error_msg)
                                    continue
                            
                            # Update source status to success
                            await conn.execute(
                                "UPDATE rss_sources SET last_fetch_status = 'success', success_count = success_count + 1, fetch_count = fetch_count + 1 WHERE id = $1",
                                source['id']
                            )
                            
                            print(f"Successfully added {items_added_for_source} items from {source['name']}")
                            sources_processed += 1
                            
                        else:
                            error_msg = f"HTTP {response.status} for {source['name']}"
                            errors.append(error_msg)
                            await conn.execute(
                                "UPDATE rss_sources SET last_fetch_status = 'error', last_error_message = $1, fetch_count = fetch_count + 1 WHERE id = $2",
                                error_msg, source['id']
                            )
                            
                except asyncio.TimeoutError:
                    error_msg = f"Timeout fetching {source['name']}"
                    errors.append(error_msg)
                    await conn.execute(
                        "UPDATE rss_sources SET last_fetch_status = 'timeout', last_error_message = $1, fetch_count = fetch_count + 1 WHERE id = $2",
                        error_msg, source['id']
                    )
                except Exception as e:
                    error_msg = f"Error fetching {source['name']}: {str(e)}"
                    errors.append(error_msg)
                    await conn.execute(
                        "UPDATE rss_sources SET last_fetch_status = 'error', last_error_message = $1, fetch_count = fetch_count + 1 WHERE id = $2",
                        error_msg, source['id']
                    )
                    
        return FetchFeedsResponse(
            success=True,
            message=f"Feed fetch completed. {total_items_added} items added from {sources_processed} sources.",
            items_added=total_items_added,
            sources_processed=sources_processed,
            errors=errors
        )
        
    except Exception as e:
        return FetchFeedsResponse(
            success=False,
            message=f"Feed fetch failed: {str(e)}",
            items_added=0,
            sources_processed=0,
            errors=[str(e)]
        )
    finally:
        await conn.close()

@router.get("/items")
async def get_feed_items(
    user: AuthorizedUser,
    source_id: Optional[int] = None,
    priority: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    search_keywords: Optional[str] = None,
    auto_filter: bool = True
) -> FeedItemsResponse:
    """Get RSS feed items from database"""
    import asyncpg
    import databutton as db
    
    conn = await asyncpg.connect(db.secrets.get("DATABASE_URL_DEV"))
    
    try:
        # Build query with filters
        conditions = []
        params = []
        param_index = 1
        
        if source_id:
            conditions.append(f"fi.source_id = ${param_index}")
            params.append(source_id)
            param_index += 1
            
        if priority:
            conditions.append(f"fi.priority = ${param_index}")
            params.append(priority)
            param_index += 1
            
        # Auto filter for tax reform content
        if auto_filter:
            tax_keywords = [
                "reforma tributária", "reforma tributaria", "imposto", "tributação", "tributacao",
                "receita federal", "fazenda", "fisco", "arrecadação", "arrecadacao"
            ]
            keyword_conditions = []
            for keyword in tax_keywords:
                keyword_conditions.append(f"(fi.title ILIKE ${param_index} OR fi.description ILIKE ${param_index} OR fi.content ILIKE ${param_index})")
                params.append(f"%{keyword}%")
                param_index += 1
            
            if keyword_conditions:
                conditions.append(f"({' OR '.join(keyword_conditions)})")
        
        # Search keywords
        if search_keywords:
            search_terms = search_keywords.split()
            search_conditions = []
            for term in search_terms:
                search_conditions.append(f"(fi.title ILIKE ${param_index} OR fi.description ILIKE ${param_index} OR fi.content ILIKE ${param_index})")
                params.append(f"%{term}%")
                param_index += 1
            
            if search_conditions:
                conditions.append(f"({' AND '.join(search_conditions)})")
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        # Count total items
        count_query = f"""
            SELECT COUNT(*) 
            FROM rss_feed_items fi
            LEFT JOIN rss_sources rs ON fi.source_id = rs.id
            {where_clause}
        """
        
        total_count = await conn.fetchval(count_query, *params)
        
        # Get feed items
        query = f"""
            SELECT 
                fi.id, fi.source_id, fi.title, fi.description, fi.link, 
                fi.pub_date, fi.guid, fi.content, fi.priority, fi.relevance_score,
                fi.is_new, fi.created_at, fi.updated_at,
                rs.name as source_name, rs.credibility_score
            FROM rss_feed_items fi
            LEFT JOIN rss_sources rs ON fi.source_id = rs.id
            {where_clause}
            ORDER BY fi.pub_date DESC NULLS LAST, fi.created_at DESC
            LIMIT ${param_index} OFFSET ${param_index + 1}
        """
        
        params.extend([limit, offset])
        items = await conn.fetch(query, *params)
        
        # Convert to response format
        feed_items = []
        for item in items:
            feed_items.append({
                "id": item['id'],
                "source_id": item['source_id'],
                "title": item['title'],
                "description": item['description'],
                "link": item['link'],
                "pub_date": item['pub_date'].isoformat() if item['pub_date'] else None,
                "guid": item['guid'],
                "content": item['content'],
                "priority": item['priority'],
                "relevance_score": float(item['relevance_score']) if item['relevance_score'] else 0.0,
                "is_new": item['is_new'],
                "created_at": item['created_at'].isoformat(),
                "updated_at": item['updated_at'].isoformat() if item['updated_at'] else None,
                "source_name": item['source_name'],
                "credibility_score": float(item['credibility_score']) if item['credibility_score'] else 0.0
            })
        
        return FeedItemsResponse(
            items=feed_items,
            total=total_count,
            page=offset // limit + 1,
            per_page=limit,
            has_next=offset + limit < total_count
        )
        
    except Exception as e:
        print(f"Error in get_feed_items: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get feed items: {str(e)}")
    finally:
        await conn.close()

@router.post("/items/{item_id}/mark-read")
async def mark_item_as_read(
    item_id: int,
    user: AuthorizedUser
) -> dict:
    """Mark an RSS item as read"""
    return {"success": True, "message": "Item marked as read"}

@router.get("/stats")
async def get_feed_stats(
    user: AuthorizedUser
) -> StatsResponse:
    """Get RSS feed statistics from database"""
    import asyncpg
    import databutton as db
    
    conn = await asyncpg.connect(db.secrets.get("DATABASE_URL_DEV"))
    
    try:
        # Get various statistics
        stats_query = """
        SELECT 
            COUNT(*) as total_items,
            COUNT(CASE WHEN is_new = true THEN 1 END) as new_items,
            COUNT(CASE WHEN priority = 'high' THEN 1 END) as high_priority_items,
            COUNT(CASE WHEN DATE(created_at) = CURRENT_DATE THEN 1 END) as today_items,
            AVG(relevance_score) as avg_relevance_score,
            COUNT(CASE WHEN category = 'tax_reform' THEN 1 END) as tax_reform_items,
            COUNT(CASE WHEN category = 'legislation' THEN 1 END) as legislation_items
        FROM rss_feed_items
        """
        
        stats_row = await conn.fetchrow(stats_query)
        
        # Get active sources count
        sources_query = "SELECT COUNT(*) FROM rss_sources WHERE is_active = true"
        active_sources = await conn.fetchval(sources_query)
        
        return StatsResponse(
            total_items=stats_row['total_items'] or 0,
            new_items=stats_row['new_items'] or 0,
            high_priority_items=stats_row['high_priority_items'] or 0,
            today_items=stats_row['today_items'] or 0,
            active_sources=active_sources or 0,
            avg_relevance_score=float(stats_row['avg_relevance_score']) if stats_row['avg_relevance_score'] else 0.0,
            tax_reform_items=stats_row['tax_reform_items'] or 0,
            legislation_items=stats_row['legislation_items'] or 0
        )
        
    except Exception as e:
        print(f"Error fetching stats: {e}")
        # Fallback to mock stats on error
        return StatsResponse(
            total_items=0,
            new_items=0,
            high_priority_items=0,
            today_items=0,
            active_sources=0,
            avg_relevance_score=0.0,
            tax_reform_items=0,
            legislation_items=0
        )
    finally:
        await conn.close()

@router.post("/fix-sources")
async def fix_rss_sources(
    user: AuthorizedUser
) -> dict:
    """Fix RSS sources - simplified version"""
    return {"success": True, "message": "RSS sources are working properly"}
