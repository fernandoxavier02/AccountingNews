from typing import List, Dict, Optional
import re
from datetime import datetime, timedelta

class PriorityScorer:
    """Advanced priority scoring system for tax reform content"""
    
    # Brazilian Tax Reform Keywords (weighted by importance)
    TAX_REFORM_KEYWORDS = {
        # High priority - core reform terms
        'reforma tributária': 100,
        'reforma tributaria': 100,
        'ibs': 95,  # Imposto sobre Bens e Serviços
        'cbs': 95,  # Contribuição sobre Bens e Serviços
        'imposto único': 90,
        'imposto unico': 90,
        'iva brasileiro': 90,
        'iva': 85,
        
        # Medium-high priority - related legislation
        'pec 45': 85,
        'pec 110': 85,
        'emenda constitucional': 80,
        'proposta de emenda': 80,
        'lei complementar': 75,
        'codigo tributario': 75,
        'código tributário': 75,
        
        # Medium priority - tax types and concepts
        'icms': 70,
        'iss': 70,
        'pis': 65,
        'cofins': 65,
        'simples nacional': 60,
        'regime tributário': 60,
        'regime tributario': 60,
        'tributação': 55,
        'tributacao': 55,
        'arrecadação': 55,
        'arrecadacao': 55,
        
        # Lower priority - general economic terms
        'imposto': 40,
        'tributo': 40,
        'receita federal': 35,
        'ministério da fazenda': 35,
        'ministerio da fazenda': 35,
        'fisco': 30,
        'contribuinte': 25,
    }
    
    # Source credibility multipliers
    SOURCE_MULTIPLIERS = {
        'receita federal': 1.0,
        'ministério da fazenda': 1.0,
        'ministerio da fazenda': 1.0,
        'senado federal': 0.95,
        'câmara dos deputados': 0.95,
        'camara dos deputados': 0.95,
        'portal da transparência': 0.85,
        'portal da transparencia': 0.85,
        'governo federal': 0.8,
        'congresso nacional': 0.9,
    }
    
    # Content categories
    CATEGORIES = {
        'tax_reform': ['reforma tributária', 'reforma tributaria', 'ibs', 'cbs', 'pec 45', 'pec 110'],
        'legislation': ['lei', 'emenda', 'proposta', 'projeto', 'medida provisória', 'medida provisoria'],
        'economy': ['economia', 'pib', 'inflação', 'inflacao', 'mercado', 'investimento'],
        'regulation': ['regulamentação', 'regulamentacao', 'norma', 'instrução', 'instrucao', 'portaria'],
        'general': []  # fallback category
    }
    
    @classmethod
    def calculate_relevance_score(cls, title: str, description: str, content: str = "") -> int:
        """Calculate content relevance score (0-100)"""
        
        # Combine all text content
        full_text = f"{title} {description} {content}".lower()
        
        # Remove special characters and normalize
        full_text = re.sub(r'[^a-záàâãéèêíìîóòôõúùûç\s]', ' ', full_text)
        full_text = re.sub(r'\s+', ' ', full_text).strip()
        
        score = 0
        matched_keywords = []
        
        # Check for keyword matches
        for keyword, weight in cls.TAX_REFORM_KEYWORDS.items():
            if keyword in full_text:
                score += weight
                matched_keywords.append(keyword)
        
        # Bonus for multiple keyword matches
        if len(matched_keywords) > 1:
            score += len(matched_keywords) * 5
        
        # Bonus for title matches (more important)
        title_lower = title.lower()
        for keyword in matched_keywords:
            if keyword in title_lower:
                score += 20
        
        # Cap at 100
        return min(score, 100)
    
    @classmethod
    def calculate_priority(cls, 
                          title: str, 
                          description: str, 
                          content: str = "",
                          source_credibility: int = 70,
                          source_name: str = "",
                          pub_date: Optional[datetime] = None) -> str:
        """Calculate final priority level (high/medium/low)"""
        
        # Get base relevance score
        relevance = cls.calculate_relevance_score(title, description, content)
        
        # Apply source credibility multiplier
        source_multiplier = 1.0
        source_lower = source_name.lower()
        for source_key, multiplier in cls.SOURCE_MULTIPLIERS.items():
            if source_key in source_lower:
                source_multiplier = multiplier
                break
        
        # Calculate credibility factor (0.7 to 1.3)
        credibility_factor = 0.7 + (source_credibility / 100) * 0.6
        
        # Apply recency bonus (newer content gets slight boost)
        recency_bonus = 0
        if pub_date:
            days_old = (datetime.utcnow() - pub_date.replace(tzinfo=None)).days
            if days_old <= 1:
                recency_bonus = 10
            elif days_old <= 7:
                recency_bonus = 5
            elif days_old <= 30:
                recency_bonus = 2
        
        # Calculate final score
        final_score = (relevance * source_multiplier * credibility_factor) + recency_bonus
        
        # Determine priority level
        if final_score >= 80:
            return 'high'
        elif final_score >= 50:
            return 'medium'
        else:
            return 'low'
    
    @classmethod
    def extract_keywords(cls, title: str, description: str, content: str = "") -> List[str]:
        """Extract relevant keywords from content"""
        
        full_text = f"{title} {description} {content}".lower()
        matched_keywords = []
        
        for keyword in cls.TAX_REFORM_KEYWORDS.keys():
            if keyword in full_text:
                matched_keywords.append(keyword)
        
        return matched_keywords
    
    @classmethod
    def categorize_content(cls, title: str, description: str, content: str = "") -> str:
        """Categorize content based on keywords"""
        
        full_text = f"{title} {description} {content}".lower()
        
        # Check each category
        for category, keywords in cls.CATEGORIES.items():
            if category == 'general':  # Skip general, it's fallback
                continue
                
            for keyword in keywords:
                if keyword in full_text:
                    return category
        
        return 'general'
    
    @classmethod
    def score_batch(cls, items: List[Dict]) -> List[Dict]:
        """Score multiple items and return enhanced data"""
        
        enhanced_items = []
        
        for item in items:
            # Calculate scores
            relevance_score = cls.calculate_relevance_score(
                item.get('title', ''),
                item.get('description', ''),
                item.get('content', '')
            )
            
            priority = cls.calculate_priority(
                item.get('title', ''),
                item.get('description', ''),
                item.get('content', ''),
                item.get('source_credibility', 70),
                item.get('source_name', ''),
                item.get('pub_date')
            )
            
            keywords = cls.extract_keywords(
                item.get('title', ''),
                item.get('description', ''),
                item.get('content', '')
            )
            
            category = cls.categorize_content(
                item.get('title', ''),
                item.get('description', ''),
                item.get('content', '')
            )
            
            # Enhance item with calculated values
            enhanced_item = item.copy()
            enhanced_item.update({
                'relevance_score': relevance_score,
                'priority': priority,
                'keywords': keywords,
                'category': category
            })
            
            enhanced_items.append(enhanced_item)
        
        return enhanced_items
