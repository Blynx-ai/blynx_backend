import asyncio
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from gemini_client import gemini_client
from db import db

logger = logging.getLogger(__name__)

class NewsAgent:
    def __init__(self):
        self.platform_name = "news_research"
    
    async def research_company_news(self, flow_id: str, business_id: int, company_name: str, industry_type: Optional[str] = None) -> Dict[str, Any]:
        """Research news about a company"""
        try:
            await self._log_news_event(flow_id, "INFO", f"Starting news research for {company_name}")
            
            # Generate search queries
            search_queries = self._generate_search_queries(company_name, industry_type)
            
            # Collect news articles
            all_articles = []
            for query in search_queries:
                await self._log_news_event(flow_id, "INFO", f"Searching for: {query}")
                articles = await self._search_news(query)
                all_articles.extend(articles)
            
            # Remove duplicates and limit results
            unique_articles = self._deduplicate_articles(all_articles)[:20]
            
            if not unique_articles:
                await self._log_news_event(flow_id, "WARNING", "No news articles found")
                return {
                    "success": False,
                    "error": "No news articles found",
                    "data": {}
                }
            
            # Analyze sentiment and extract insights
            await self._log_news_event(flow_id, "INFO", f"Analyzing {len(unique_articles)} articles")
            analysis_result = await self._analyze_news_articles(unique_articles, company_name, industry_type)
            
            # Save to database
            news_research_id = await self._save_news_research(
                flow_id, business_id, company_name, search_queries, 
                unique_articles, analysis_result
            )
            
            await self._log_news_event(flow_id, "INFO", "News research completed successfully")
            
            return {
                "success": True,
                "data": {
                    "research_id": news_research_id,
                    "company_name": company_name,
                    "total_articles": len(unique_articles),
                    "search_queries": search_queries,
                    "articles": unique_articles,
                    "analysis": analysis_result,
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Error in news research: {str(e)}")
            await self._log_news_event(flow_id, "ERROR", f"News research failed: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "data": {}
            }
    
    def _generate_search_queries(self, company_name: str, industry_type: Optional[str] = None) -> List[str]:
        """Generate search queries for news research"""
        queries = [
            f'"{company_name}" news',
            f'"{company_name}" announcement',
            f'"{company_name}" press release',
        ]
        
        if industry_type:
            queries.extend([
                f'"{company_name}" {industry_type}',
                f'"{company_name}" {industry_type} news'
            ])
        
        return queries
    
    async def _search_news(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search for news articles using a simple approach"""
        # Note: In production, you would use a proper news API like NewsAPI, Google News API, etc.
        # For now, we'll simulate news search results
        
        try:
            # This is a simplified approach - in production use proper news APIs
            articles = []
            
            # Simulate some news articles (replace with actual API calls)
            simulated_articles = [
                {
                    "title": f"Latest developments at {query.split()[0]}",
                    "description": f"Recent news and updates about {query.split()[0]} in the industry",
                    "url": f"https://example-news.com/article-{hash(query) % 1000}",
                    "published_date": (datetime.utcnow() - timedelta(days=1)).isoformat(),
                    "source": "Example News",
                    "sentiment": "neutral"
                },
                {
                    "title": f"{query.split()[0]} announces new initiative",
                    "description": f"Company makes strategic announcement affecting market position",
                    "url": f"https://business-news.com/story-{hash(query) % 2000}",
                    "published_date": (datetime.utcnow() - timedelta(days=5)).isoformat(),
                    "source": "Business News",
                    "sentiment": "positive"
                }
            ]
            
            # In production, replace above with actual news API calls like:
            # response = requests.get(f"https://newsapi.org/v2/everything?q={query}&apiKey={API_KEY}")
            # articles = response.json().get('articles', [])
            
            return simulated_articles[:max_results]
            
        except Exception as e:
            logger.error(f"Error searching news: {str(e)}")
            return []
    
    def _deduplicate_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate articles based on title similarity"""
        unique_articles = []
        seen_titles = set()
        
        for article in articles:
            title = article.get('title', '').lower().strip()
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique_articles.append(article)
        
        return unique_articles
    
    async def _analyze_news_articles(self, articles: List[Dict[str, Any]], company_name: str, industry_type: Optional[str] = None) -> Dict[str, Any]:
        """Analyze news articles for sentiment and insights"""
        try:
            articles_text = json.dumps(articles, indent=2)
            
            prompt = f"""
            Analyze the following news articles about {company_name} ({industry_type or 'unspecified industry'}):

            Articles: {articles_text}

            Provide a JSON response with:
            1. overall_sentiment: (positive/neutral/negative)
            2. sentiment_score: (0-100, where 100 is most positive)
            3. key_themes: [list of main themes found in articles]
            4. positive_mentions: [list of positive aspects mentioned]
            5. negative_mentions: [list of negative aspects mentioned]
            6. neutral_mentions: [list of neutral/factual mentions]
            7. market_impact_indicators: [any indicators of market impact]
            8. competitive_mentions: [mentions of competitors]
            9. future_outlook_indicators: [any indicators about future prospects]
            10. credibility_assessment: (high/medium/low credibility of sources)
            11. article_quality_score: (0-100)
            12. key_insights: [important insights derived from the news]
            13. risk_indicators: [any risk factors mentioned]
            14. opportunity_indicators: [any opportunities mentioned]
            """
            
            result = await gemini_client.generate_json_content(prompt)
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing news articles: {str(e)}")
            return {
                "error": str(e),
                "overall_sentiment": "neutral",
                "sentiment_score": 50
            }
    
    async def _save_news_research(self, flow_id: str, business_id: int, company_name: str, 
                                 search_queries: List[str], articles: List[Dict], 
                                 analysis: Dict[str, Any]) -> int:
        """Save news research results to database"""
        try:
            async with db.get_connection() as conn:
                news_research_id = await conn.fetchval(
                    """
                    INSERT INTO news_research (
                        flow_id, business_id, company_name, search_query, 
                        news_articles, sentiment_analysis, key_insights, 
                        status, total_articles
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING id
                    """,
                    flow_id, business_id, company_name, json.dumps(search_queries),
                    json.dumps(articles), json.dumps(analysis), 
                    json.dumps(analysis.get('key_insights', [])),
                    'completed', len(articles)
                )
                return news_research_id
        except Exception as e:
            logger.error(f"Error saving news research: {str(e)}")
            return 0
    
    async def _log_news_event(self, flow_id: str, level: str, message: str):
        """Log news research events"""
        if not flow_id:
            logger.info(f"News Agent: {message}")
            return
            
        try:
            async with db.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO flow_logs (flow_id, agent_type, log_level, message)
                    VALUES ($1, $2, $3, $4)
                    """,
                    flow_id, "NEWS_AGENT", level, message
                )
        except Exception as e:
            logger.error(f"Error logging news event: {str(e)}")

# Global news agent instance
news_agent = NewsAgent()