import re
from typing import List, Dict, Optional
from dataclasses import dataclass

@dataclass
class FilterResult:
    """Result of content filtering"""
    is_relevant: bool
    relevance_score: int
    matched_keywords: List[str]
    filter_reason: Optional[str] = None

class TaxReformContentFilter:
    """Intelligent content filter for Brazilian Tax Reform news"""
    
    def __init__(self):
        # Primary keywords - must have at least one
        self.primary_keywords = [
            "reforma tributária",
            "reforma tributaria",  # without accent
            "ibs",  # Imposto sobre Bens e Serviços
            "cbs",  # Contribuição sobre Bens e Serviços
        ]
        
        # Secondary keywords - boost relevance score
        self.secondary_keywords = [
            "imposto sobre bens e serviços",
            "contribuição sobre bens e serviços",
            "sistema tributário nacional",
            "código tributário nacional",
            "simplificação tributária",
            "unificação de impostos",
            "icms", "iss", "pis", "cofins",
            "ministério da fazenda",
            "receita federal",
            "congresso nacional",
            "proposta de emenda constitucional",
            "pec",
            "emenda constitucional",
            "tributação",
            "arrecadação"
        ]
        
        # Exclusion keywords - reduce relevance or exclude
        self.exclusion_keywords = [
            "esporte", "futebol", "música", "entretenimento",
            "celebridade", "novela", "filme", "show",
            "crime", "acidente", "trânsito",
            "meteorologia", "tempo", "chuva"
        ]
    
    def normalize_text(self, text: str) -> str:
        """Normalize text for keyword matching"""
        if not text:
            return ""
        
        # Convert to lowercase and remove extra spaces
        text = text.lower().strip()
        
        # Remove accents and special characters for better matching
        text = re.sub(r'[àáâãäå]', 'a', text)
        text = re.sub(r'[èéêë]', 'e', text)
        text = re.sub(r'[ìíîï]', 'i', text)
        text = re.sub(r'[òóôõö]', 'o', text)
        text = re.sub(r'[ùúûü]', 'u', text)
        text = re.sub(r'[ç]', 'c', text)
        
        return text
    
    def count_keyword_matches(self, text: str, keywords: List[str]) -> Dict[str, int]:
        """Count matches for each keyword in text"""
        normalized_text = self.normalize_text(text)
        matches = {}
        
        for keyword in keywords:
            normalized_keyword = self.normalize_text(keyword)
            # Use word boundaries for exact matches
            pattern = r'\b' + re.escape(normalized_keyword) + r'\b'
            count = len(re.findall(pattern, normalized_text))
            if count > 0:
                matches[keyword] = count
        
        return matches
    
    def calculate_relevance_score(self, 
                                primary_matches: Dict[str, int],
                                secondary_matches: Dict[str, int],
                                exclusion_matches: Dict[str, int]) -> int:
        """Calculate relevance score based on keyword matches"""
        
        # Base score for primary keywords
        primary_score = sum(count * 20 for count in primary_matches.values())
        
        # Bonus for secondary keywords
        secondary_score = sum(count * 5 for count in secondary_matches.values())
        
        # Penalty for exclusion keywords
        exclusion_penalty = sum(count * 10 for count in exclusion_matches.values())
        
        # Bonus for multiple different primary keywords
        if len(primary_matches) > 1:
            primary_score += 15
        
        # Calculate final score
        final_score = primary_score + secondary_score - exclusion_penalty
        
        # Ensure score is between 0 and 100
        return max(0, min(100, final_score))
    
    def filter_content(self, title: str, description: str = None, content: str = None) -> FilterResult:
        """Filter content and return relevance assessment"""
        
        # Combine all text for analysis
        full_text = f"{title or ''} {description or ''} {content or ''}"
        
        if not full_text.strip():
            return FilterResult(
                is_relevant=False,
                relevance_score=0,
                matched_keywords=[],
                filter_reason="No content to analyze"
            )
        
        # Count keyword matches
        primary_matches = self.count_keyword_matches(full_text, self.primary_keywords)
        secondary_matches = self.count_keyword_matches(full_text, self.secondary_keywords)
        exclusion_matches = self.count_keyword_matches(full_text, self.exclusion_keywords)
        
        # Calculate relevance score
        relevance_score = self.calculate_relevance_score(
            primary_matches, secondary_matches, exclusion_matches
        )
        
        # Determine if content is relevant
        # Must have at least one primary keyword and score above threshold
        has_primary_keyword = len(primary_matches) > 0
        min_score_threshold = 15  # Minimum score to be considered relevant
        
        is_relevant = has_primary_keyword and relevance_score >= min_score_threshold
        
        # Collect all matched keywords
        all_matched = list(primary_matches.keys()) + list(secondary_matches.keys())
        
        # Set filter reason if not relevant
        filter_reason = None
        if not is_relevant:
            if not has_primary_keyword:
                filter_reason = "No tax reform keywords found"
            elif relevance_score < min_score_threshold:
                filter_reason = f"Low relevance score: {relevance_score}"
        
        return FilterResult(
            is_relevant=is_relevant,
            relevance_score=relevance_score,
            matched_keywords=all_matched,
            filter_reason=filter_reason
        )
    
    def filter_items_list(self, items: List[Dict]) -> List[Dict]:
        """Filter a list of feed items, keeping only relevant ones"""
        filtered_items = []
        
        for item in items:
            title = item.get('title', '')
            description = item.get('description', '')
            content = item.get('content', '')
            
            filter_result = self.filter_content(title, description, content)
            
            if filter_result.is_relevant:
                # Add filter metadata to item
                item['relevance_score'] = filter_result.relevance_score
                item['matched_keywords'] = filter_result.matched_keywords
                filtered_items.append(item)
        
        # Sort by relevance score (highest first)
        filtered_items.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        
        return filtered_items

# Global instance
tax_reform_filter = TaxReformContentFilter()
