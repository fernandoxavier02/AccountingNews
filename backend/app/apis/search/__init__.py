from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import asyncpg
import databutton as db
from datetime import datetime, date
from app.auth import AuthorizedUser
from app.libs.access_middleware import verify_email_authorization
import re
import json

router = APIRouter()

class SearchFilters(BaseModel):
    """Advanced search filters"""
    date_from: Optional[date] = Field(None, description="Start date for filtering")
    date_to: Optional[date] = Field(None, description="End date for filtering")
    source_ids: Optional[List[int]] = Field(None, description="Filter by specific RSS sources")
    categories: Optional[List[str]] = Field(None, description="Filter by content categories")
    priorities: Optional[List[str]] = Field(None, description="Filter by priority levels")
    min_relevance: Optional[int] = Field(None, ge=0, le=100, description="Minimum relevance score")
    keywords: Optional[List[str]] = Field(None, description="Must include these keywords")
    exclude_keywords: Optional[List[str]] = Field(None, description="Must exclude these keywords")
    bookmarked_only: Optional[bool] = Field(False, description="Show only bookmarked items")

class SearchRequest(BaseModel):
    """Search request payload"""
    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    filters: Optional[SearchFilters] = Field(None, description="Advanced filters")
    page: int = Field(1, ge=1, description="Page number")
    per_page: int = Field(20, ge=1, le=100, description="Items per page")
    sort_by: str = Field('relevance', description="Sort by: relevance, date, priority")
    sort_order: str = Field('desc', description="Sort order: asc or desc")
    highlight: bool = Field(True, description="Enable search term highlighting")

class SearchResult(BaseModel):
    """Individual search result item"""
    id: int
    source_id: int
    source_name: Optional[str]
    title: str
    description: Optional[str]
    content: Optional[str]
    link: str
    pub_date: Optional[datetime]
    priority: str
    relevance_score: int
    keywords: List[str]
    category: str
    is_bookmarked: bool
    created_at: datetime
    # Highlighted versions for search results
    title_highlighted: Optional[str] = None
    description_highlighted: Optional[str] = None
    content_highlighted: Optional[str] = None
    search_rank: Optional[float] = None

class SearchResponse(BaseModel):
    """Search response with results and metadata"""
    results: List[SearchResult]
    total_results: int
    page: int
    per_page: int
    total_pages: int
    search_time_ms: float
    suggested_terms: List[str] = []
    facets: Dict[str, Any] = {}

class SearchSuggestionsResponse(BaseModel):
    """Search suggestions response"""
    suggestions: List[str]
    popular_searches: List[Dict[str, Any]]

class SearchAnalyticsResponse(BaseModel):
    """Search analytics response"""
    popular_terms: List[Dict[str, Any]]
    recent_searches: List[Dict[str, Any]]
    search_trends: List[Dict[str, Any]]
    total_searches: int

def sanitize_search_query(query: str) -> str:
    """Sanitize and prepare search query for PostgreSQL full-text search"""
    # Remove special characters that could break the query
    query = re.sub(r'[<>()&|!]', ' ', query)
    # Split into words and join with & for AND search
    words = [word.strip() for word in query.split() if word.strip()]
    if not words:
        return ''
    # Use | for OR search, & for AND search
    return ' & '.join(words)

def highlight_text(text: str, query: str) -> str:
    """Add HTML highlighting to search terms in text"""
    if not text or not query:
        return text
    
    words = [word.strip() for word in query.split() if word.strip()]
    highlighted = text
    
    for word in words:
        # Case-insensitive highlighting
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        highlighted = pattern.sub(f'<mark>{word}</mark>', highlighted)
    
    return highlighted

async def get_db_connection():
    """Get database connection"""
    return await asyncpg.connect(db.secrets.get("DATABASE_URL_DEV"))

async def record_search_analytics(search_term: str, results_count: int):
    """Record search analytics"""
    conn = await get_db_connection()
    try:
        # Update or insert search analytics
        await conn.execute("""
            INSERT INTO search_analytics (search_term, search_count, results_count, last_searched)
            VALUES ($1, 1, $2, NOW())
            ON CONFLICT (search_term) 
            DO UPDATE SET 
                search_count = search_analytics.search_count + 1,
                results_count = $2,
                last_searched = NOW()
        """, search_term.lower(), results_count)
    finally:
        await conn.close()

async def record_user_search_history(user_id: str, search_term: str, filters: Dict, results_count: int):
    """Record individual user search history"""
    conn = await get_db_connection()
    try:
        await conn.execute("""
            INSERT INTO search_history (user_id, search_term, filters, results_count, searched_at)
            VALUES ($1, $2, $3, $4, NOW())
        """, user_id, search_term, json.dumps(filters), results_count)
    finally:
        await conn.close()

@router.post("/search")
async def search_content(
    request: SearchRequest,
    user: AuthorizedUser = verify_email_authorization
) -> SearchResponse:
    """Search through RSS feed content with advanced filtering and highlighting"""
    start_time = datetime.now()
    
    try:
        conn = await get_db_connection()
        
        # Sanitize search query
        sanitized_query = sanitize_search_query(request.query)
        if not sanitized_query:
            raise HTTPException(status_code=400, detail="Invalid search query")
        
        # Build the base query
        base_query = """
            SELECT 
                fi.id, fi.source_id, fi.title, fi.description, fi.content, fi.link,
                fi.pub_date, fi.priority, fi.relevance_score, fi.keywords, fi.category,
                fi.created_at, rs.name as source_name,
                ts_rank_cd(
                    to_tsvector('portuguese', fi.title || ' ' || COALESCE(fi.description, '') || ' ' || COALESCE(fi.content, '')),
                    to_tsquery('portuguese', $1)
                ) as search_rank,
                CASE WHEN ub.id IS NOT NULL THEN true ELSE false END as is_bookmarked
            FROM rss_feed_items fi
            LEFT JOIN rss_sources rs ON fi.source_id = rs.id
            LEFT JOIN user_bookmarks ub ON fi.id = ub.feed_item_id AND ub.user_id = $2
            WHERE to_tsvector('portuguese', fi.title || ' ' || COALESCE(fi.description, '') || ' ' || COALESCE(fi.content, '')) 
                  @@ to_tsquery('portuguese', $1)
        """
        
        # Parameters list
        params = [sanitized_query, user.sub if user else '']
        param_index = 3
        
        # Add filters
        filter_conditions = []
        
        if request.filters:
            if request.filters.date_from:
                filter_conditions.append(f"fi.pub_date >= ${param_index}")
                params.append(request.filters.date_from)
                param_index += 1
            
            if request.filters.date_to:
                filter_conditions.append(f"fi.pub_date <= ${param_index}")
                params.append(request.filters.date_to)
                param_index += 1
            
            if request.filters.source_ids:
                filter_conditions.append(f"fi.source_id = ANY(${param_index})")
                params.append(request.filters.source_ids)
                param_index += 1
            
            if request.filters.categories:
                filter_conditions.append(f"fi.category = ANY(${param_index})")
                params.append(request.filters.categories)
                param_index += 1
            
            if request.filters.priorities:
                filter_conditions.append(f"fi.priority = ANY(${param_index})")
                params.append(request.filters.priorities)
                param_index += 1
            
            if request.filters.min_relevance is not None:
                filter_conditions.append(f"fi.relevance_score >= ${param_index}")
                params.append(request.filters.min_relevance)
                param_index += 1
            
            if request.filters.keywords:
                # Keywords must be present
                filter_conditions.append(f"fi.keywords && ${param_index}")
                params.append(request.filters.keywords)
                param_index += 1
            
            if request.filters.exclude_keywords:
                # Keywords must NOT be present
                filter_conditions.append(f"NOT (fi.keywords && ${param_index})")
                params.append(request.filters.exclude_keywords)
                param_index += 1
            
            if request.filters.bookmarked_only and user:
                filter_conditions.append("ub.id IS NOT NULL")
        
        # Add filter conditions to query
        if filter_conditions:
            base_query += " AND " + " AND ".join(filter_conditions)
        
        # Add sorting
        sort_column = {
            'relevance': 'search_rank',
            'date': 'fi.pub_date',
            'priority': 'fi.priority'
        }.get(request.sort_by, 'search_rank')
        
        sort_direction = 'ASC' if request.sort_order.lower() == 'asc' else 'DESC'
        base_query += f" ORDER BY {sort_column} {sort_direction}"
        
        # Get total count
        count_query = f"""
            SELECT COUNT(*) FROM (
                {base_query}
            ) as count_subquery
        """
        
        total_results = await conn.fetchval(count_query, *params)
        
        # Add pagination
        offset = (request.page - 1) * request.per_page
        paginated_query = base_query + f" LIMIT ${param_index} OFFSET ${param_index + 1}"
        params.extend([request.per_page, offset])
        
        # Execute search
        rows = await conn.fetch(paginated_query, *params)
        
        # Process results
        results = []
        for row in rows:
            result = SearchResult(
                id=row['id'],
                source_id=row['source_id'],
                source_name=row['source_name'],
                title=row['title'],
                description=row['description'],
                content=row['content'],
                link=row['link'],
                pub_date=row['pub_date'],
                priority=row['priority'],
                relevance_score=row['relevance_score'],
                keywords=list(row['keywords']) if row['keywords'] else [],
                category=row['category'],
                is_bookmarked=row['is_bookmarked'],
                created_at=row['created_at'],
                search_rank=float(row['search_rank']) if row['search_rank'] else 0.0
            )
            
            # Add highlighting if requested
            if request.highlight:
                result.title_highlighted = highlight_text(result.title, request.query)
                result.description_highlighted = highlight_text(result.description or '', request.query)
                result.content_highlighted = highlight_text(result.content or '', request.query)
            
            results.append(result)
        
        await conn.close()
        
        # Calculate metrics
        end_time = datetime.now()
        search_time_ms = (end_time - start_time).total_seconds() * 1000
        total_pages = (total_results + request.per_page - 1) // request.per_page
        
        # Record analytics
        await record_search_analytics(request.query, total_results)
        if user:
            filters_dict = request.filters.dict() if request.filters else {}
            await record_user_search_history(user.sub, request.query, filters_dict, total_results)
        
        # Get facets (aggregations)
        facets = await get_search_facets(sanitized_query, user.sub if user else '')
        
        return SearchResponse(
            results=results,
            total_results=total_results,
            page=request.page,
            per_page=request.per_page,
            total_pages=total_pages,
            search_time_ms=search_time_ms,
            facets=facets
        )
        
    except Exception as e:
        print(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

async def get_search_facets(query: str, user_id: str) -> Dict[str, Any]:
    """Get search facets/aggregations"""
    conn = await get_db_connection()
    try:
        # Get category distribution
        category_facets = await conn.fetch("""
            SELECT fi.category, COUNT(*) as count
            FROM rss_feed_items fi
            WHERE to_tsvector('portuguese', fi.title || ' ' || COALESCE(fi.description, '') || ' ' || COALESCE(fi.content, '')) 
                  @@ to_tsquery('portuguese', $1)
            GROUP BY fi.category
            ORDER BY count DESC
        """, query)
        
        # Get source distribution
        source_facets = await conn.fetch("""
            SELECT rs.name, COUNT(*) as count
            FROM rss_feed_items fi
            LEFT JOIN rss_sources rs ON fi.source_id = rs.id
            WHERE to_tsvector('portuguese', fi.title || ' ' || COALESCE(fi.description, '') || ' ' || COALESCE(fi.content, '')) 
                  @@ to_tsquery('portuguese', $1)
            GROUP BY rs.name
            ORDER BY count DESC
        """, query)
        
        # Get priority distribution
        priority_facets = await conn.fetch("""
            SELECT fi.priority, COUNT(*) as count
            FROM rss_feed_items fi
            WHERE to_tsvector('portuguese', fi.title || ' ' || COALESCE(fi.description, '') || ' ' || COALESCE(fi.content, '')) 
                  @@ to_tsquery('portuguese', $1)
            GROUP BY fi.priority
            ORDER BY count DESC
        """, query)
        
        return {
            'categories': [{'name': row['category'], 'count': row['count']} for row in category_facets],
            'sources': [{'name': row['name'], 'count': row['count']} for row in source_facets],
            'priorities': [{'name': row['priority'], 'count': row['count']} for row in priority_facets]
        }
    finally:
        await conn.close()

@router.get("/suggestions")
async def get_search_suggestions(
    query: str = Query(..., description="Search query for suggestions"),
    user: AuthorizedUser = verify_email_authorization
) -> SearchSuggestionsResponse:
    """Get search suggestions based on popular searches and content"""
    try:
        conn = await get_db_connection()
        
        # Get suggestions from popular search terms
        popular_searches = await conn.fetch("""
            SELECT search_term, search_count
            FROM search_analytics
            WHERE search_term ILIKE $1
            ORDER BY search_count DESC
            LIMIT $2
        """, f"%{query.lower()}%", 10)
        
        # Get suggestions from content keywords
        keyword_suggestions = await conn.fetch("""
            SELECT DISTINCT unnest(keywords) as keyword, COUNT(*) as frequency
            FROM rss_feed_items
            WHERE unnest(keywords) ILIKE $1
            GROUP BY keyword
            ORDER BY frequency DESC
            LIMIT $2
        """, f"%{query.lower()}%", 10)
        
        # Combine and format suggestions
        suggestions = []
        for row in popular_searches:
            suggestions.append(row['search_term'])
        
        for row in keyword_suggestions:
            if row['keyword'] not in suggestions:
                suggestions.append(row['keyword'])
        
        await conn.close()
        
        return SearchSuggestionsResponse(
            suggestions=suggestions[:10],
            popular_searches=[
                {'term': row['search_term'], 'count': row['search_count']} 
                for row in popular_searches
            ]
        )
        
    except Exception as e:
        print(f"Suggestions error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get suggestions: {str(e)}")

@router.get("/analytics")
async def get_search_analytics(
    period: str = Query("7d", description="Time period for analytics"),
    user: AuthorizedUser = verify_email_authorization
) -> SearchAnalyticsResponse:
    """Get search analytics and trends"""
    try:
        conn = await get_db_connection()
        
        # Get popular search terms
        popular_terms = await conn.fetch("""
            SELECT search_term, search_count, last_searched
            FROM search_analytics
            WHERE last_searched >= NOW() - INTERVAL '%s days'
            ORDER BY search_count DESC
            LIMIT 20
        """ % period)
        
        # Get user's recent searches
        recent_searches = await conn.fetch("""
            SELECT search_term, searched_at, results_count
            FROM search_history
            WHERE user_id = $1 AND searched_at >= NOW() - INTERVAL '%s days'
            ORDER BY searched_at DESC
            LIMIT 10
        """ % period, user.sub)
        
        # Get search trends (daily aggregation)
        search_trends = await conn.fetch("""
            SELECT DATE(searched_at) as date, COUNT(*) as searches
            FROM search_history
            WHERE searched_at >= NOW() - INTERVAL '%s days'
            GROUP BY DATE(searched_at)
            ORDER BY date DESC
        """ % period)
        
        # Get total searches count
        total_searches = await conn.fetchval("""
            SELECT COUNT(*) FROM search_history
            WHERE searched_at >= NOW() - INTERVAL '%s days'
        """ % period)
        
        await conn.close()
        
        return SearchAnalyticsResponse(
            popular_terms=[
                {
                    'term': row['search_term'],
                    'count': row['search_count'],
                    'last_searched': row['last_searched']
                }
                for row in popular_terms
            ],
            recent_searches=[
                {
                    'term': row['search_term'],
                    'searched_at': row['searched_at'],
                    'results': row['results_count']
                }
                for row in recent_searches
            ],
            search_trends=[
                {
                    'date': row['date'],
                    'searches': row['searches']
                }
                for row in search_trends
            ],
            total_searches=total_searches or 0
        )
        
    except Exception as e:
        print(f"Analytics error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get analytics: {str(e)}")
