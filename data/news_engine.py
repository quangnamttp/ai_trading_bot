"""
Module News Engine cho AI Trading Signal Bot
Thu thập tin tức Crypto và Forex từ nhiều nguồn
"""
import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from ..core.config import NEWS_API_KEY

logger = logging.getLogger(__name__)


class NewsEngine:
    """Thu thập và xử lý tin tức thị trường"""
    
    def __init__(self):
        self.news_cache = []
        self.last_update = None
        self.economic_calendar = []
    
    async def fetch_crypto_news(self) -> List[Dict]:
        """Lấy tin tức Crypto"""
        try:
            news = []
            
            # Sử dụng NewsAPI (nếu có key)
            if NEWS_API_KEY:
                url = f"https://newsapi.org/v2/everything?q=cryptocurrency+OR+bitcoin+OR+ethereum&apiKey={NEWS_API_KEY}&language=en&sortBy=publishedAt&pageSize=10"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            for article in data.get('articles', []):
                                news.append({
                                    'title': article.get('title'),
                                    'description': article.get('description'),
                                    'url': article.get('url'),
                                    'published_at': article.get('publishedAt'),
                                    'source': article.get('source', {}).get('name'),
                                    'category': 'crypto'
                                })
            
            # Nếu không có API key, sử dụng dữ liệu mẫu
            if not news:
                news = self._get_sample_crypto_news()
            
            logger.info(f"Fetched {len(news)} crypto news articles")
            return news
        except Exception as e:
            logger.error(f"Error fetching crypto news: {e}")
            return self._get_sample_crypto_news()
    
    async def fetch_forex_news(self) -> List[Dict]:
        """Lấy tin tức Forex"""
        try:
            news = []
            
            # Sử dụng NewsAPI
            if NEWS_API_KEY:
                url = f"https://newsapi.org/v2/everything?q=forex+OR+trading+OR+economy&apiKey={NEWS_API_KEY}&language=en&sortBy=publishedAt&pageSize=10"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            for article in data.get('articles', []):
                                news.append({
                                    'title': article.get('title'),
                                    'description': article.get('description'),
                                    'url': article.get('url'),
                                    'published_at': article.get('publishedAt'),
                                    'source': article.get('source', {}).get('name'),
                                    'category': 'forex'
                                })
            
            if not news:
                news = self._get_sample_forex_news()
            
            logger.info(f"Fetched {len(news)} forex news articles")
            return news
        except Exception as e:
            logger.error(f"Error fetching forex news: {e}")
            return self._get_sample_forex_news()
    
    async def fetch_economic_calendar(self) -> List[Dict]:
        """Lấy lịch kinh tế (FOMC, CPI, PPI, NFP)"""
        try:
            # Dữ liệu mẫu - trong thực tế cần API từ Forex Factory hoặc Trading Economics
            calendar = [
                {
                    'event': 'FOMC Meeting',
                    'date': (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d'),
                    'importance': 'high',
                    'currency': 'USD',
                    'impact': 'high'
                },
                {
                    'event': 'CPI Data',
                    'date': (datetime.now() + timedelta(days=14)).strftime('%Y-%m-%d'),
                    'importance': 'high',
                    'currency': 'USD',
                    'impact': 'high'
                },
                {
                    'event': 'NFP Report',
                    'date': (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d'),
                    'importance': 'high',
                    'currency': 'USD',
                    'impact': 'high'
                }
            ]
            
            self.economic_calendar = calendar
            logger.info(f"Fetched {len(calendar)} economic calendar events")
            return calendar
        except Exception as e:
            logger.error(f"Error fetching economic calendar: {e}")
            return []
    
    async def get_fear_greed_index(self) -> Optional[Dict]:
        """Lấy chỉ số Fear & Greed"""
        try:
            # API từ Alternative.me
            url = "https://api.alternative.me/fng/"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('data'):
                            fng_data = data['data'][0]
                            return {
                                'value': int(fng_data.get('value')),
                                'classification': fng_data.get('value_classification'),
                                'timestamp': fng_data.get('timestamp')
                            }
        except Exception as e:
            logger.error(f"Error fetching Fear & Greed index: {e}")
        
        # Dữ liệu mẫu nếu API lỗi
        return {
            'value': 65,
            'classification': 'Greed',
            'timestamp': datetime.now().isoformat()
        }
    
    async def get_dxy_index(self) -> Optional[Dict]:
        """Lấy chỉ số DXY (US Dollar Index)"""
        try:
            # Dữ liệu mẫu - trong thực tế cần API từ trading platform
            return {
                'value': 104.5,
                'change': 0.2,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error fetching DXY index: {e}")
            return None
    
    async def get_bond_yields(self) -> Optional[Dict]:
        """Lấy lợi suất trái phiếu"""
        try:
            # Dữ liệu mẫu
            return {
                '10y_treasury': 4.2,
                '2y_treasury': 4.8,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error fetching bond yields: {e}")
            return None
    
    async def get_bitcoin_etf_flow(self) -> Optional[Dict]:
        """Lấy dòng tiền ETF Bitcoin"""
        try:
            # Dữ liệu mẫu
            return {
                'net_flow': 150000000,  # $150M
                'total_aum': 50000000000,  # $50B
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error fetching Bitcoin ETF flow: {e}")
            return None
    
    async def update_news(self):
        """Cập nhật tin tức mới"""
        try:
            crypto_news = await self.fetch_crypto_news()
            forex_news = await self.fetch_forex_news()
            
            all_news = crypto_news + forex_news
            
            # Sắp xếp theo thời gian
            all_news.sort(key=lambda x: x.get('published_at', ''), reverse=True)
            
            self.news_cache = all_news[:50]  # Giữ 50 tin mới nhất
            self.last_update = datetime.now()
            
            logger.info(f"Updated news cache: {len(self.news_cache)} articles")
        except Exception as e:
            logger.error(f"Error updating news: {e}")
    
    async def get_important_news(self, hours: int = 24) -> List[Dict]:
        """Lấy tin tức quan trọng trong X giờ qua"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            
            important_news = []
            for news in self.news_cache:
                published_at = news.get('published_at')
                if published_at:
                    try:
                        pub_time = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                        if pub_time > cutoff_time:
                            important_news.append(news)
                    except:
                        pass
            
            return important_news
        except Exception as e:
            logger.error(f"Error getting important news: {e}")
            return []
    
    def _get_sample_crypto_news(self) -> List[Dict]:
        """Dữ liệu tin tức Crypto mẫu"""
        return [
            {
                'title': 'Bitcoin ETF sees record inflows',
                'description': 'Spot Bitcoin ETFs attracted over $500M in inflows yesterday.',
                'url': '#',
                'published_at': datetime.now().isoformat(),
                'source': 'CryptoNews',
                'category': 'crypto'
            },
            {
                'title': 'Fed signals potential rate cuts',
                'description': 'Federal Reserve officials suggest rate cuts may come in 2024.',
                'url': '#',
                'published_at': (datetime.now() - timedelta(hours=2)).isoformat(),
                'source': 'FinanceNews',
                'category': 'crypto'
            },
            {
                'title': 'Institutional adoption of crypto grows',
                'description': 'Major banks increase crypto custody services.',
                'url': '#',
                'published_at': (datetime.now() - timedelta(hours=5)).isoformat(),
                'source': 'CryptoDaily',
                'category': 'crypto'
            }
        ]
    
    def _get_sample_forex_news(self) -> List[Dict]:
        """Dữ liệu tin tức Forex mẫu"""
        return [
            {
                'title': 'DXY strengthens on economic data',
                'description': 'US Dollar Index gains as economic data exceeds expectations.',
                'url': '#',
                'published_at': datetime.now().isoformat(),
                'source': 'ForexNews',
                'category': 'forex'
            },
            {
                'title': 'Gold prices surge amid geopolitical tension',
                'description': 'Safe-haven demand pushes gold prices higher.',
                'url': '#',
                'published_at': (datetime.now() - timedelta(hours=3)).isoformat(),
                'source': 'MarketWatch',
                'category': 'forex'
            },
            {
                'title': 'ECB holds rates steady',
                'description': 'European Central Bank maintains current interest rates.',
                'url': '#',
                'published_at': (datetime.now() - timedelta(hours=6)).isoformat(),
                'source': 'Bloomberg',
                'category': 'forex'
            }
        ]
    
    async def get_news_summary(self) -> str:
        """Lấy tóm tắt tin tức"""
        try:
            important_news = await self.get_important_news(hours=24)
            fear_greed = await self.get_fear_greed_index()
            
            summary = "📰 *Tin tức thị trường 24h qua*\n\n"
            
            if important_news:
                summary += "🔹 *Crypto News:*\n"
                for news in important_news[:3]:
                    if news.get('category') == 'crypto':
                        summary += f"• {news.get('title', 'N/A')}\n"
                        summary += f"  {news.get('description', 'N/A')[:100]}...\n\n"
                
                summary += "🔹 *Forex News:*\n"
                for news in important_news[:3]:
                    if news.get('category') == 'forex':
                        summary += f"• {news.get('title', 'N/A')}\n"
                        summary += f"  {news.get('description', 'N/A')[:100]}...\n\n"
            
            if fear_greed:
                summary += f"😰 *Fear & Greed Index:* {fear_greed['value']} - {fear_greed['classification']}\n"
            
            if self.economic_calendar:
                summary += "\n📅 *Sự kiện sắp tới:*\n"
                for event in self.economic_calendar[:3]:
                    summary += f"• {event['event']} - {event['date']} ({event['importance']})\n"
            
            return summary
        except Exception as e:
            logger.error(f"Error getting news summary: {e}")
            return "❌ Không thể lấy tin tức"


# Singleton instance
news_engine = NewsEngine()
