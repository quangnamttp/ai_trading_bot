"""
Module News Engine cho AI Trading Signal Bot
Thu thập tin tức Crypto quan trọng từ các nguồn RSS công khai (KHÔNG cần API key)
và tự động dịch sang tiếng Việt.

Nguồn: CoinDesk, Cointelegraph, Decrypt (RSS công khai, miễn phí, không giới hạn key)
Nếu có NEWS_API_KEY (tùy chọn), bot sẽ dùng thêm NewsAPI để có nhiều nguồn hơn.
"""
import logging
import asyncio
import re
import aiohttp
import feedparser
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from core.config import NEWS_API_KEY

logger = logging.getLogger(__name__)

# Các nguồn RSS công khai, không cần API key
RSS_FEEDS = {
    'CoinDesk': 'https://www.coindesk.com/arc/outboundfeeds/rss/',
    'Cointelegraph': 'https://cointelegraph.com/rss',
    'Decrypt': 'https://decrypt.co/feed',
}

# Từ khóa để chấm điểm mức độ QUAN TRỌNG / ảnh hưởng thị trường của 1 tin tức.
# Điểm càng cao càng có khả năng gây biến động giá mạnh.
IMPORTANCE_KEYWORDS = {
    # Vĩ mô / Ngân hàng trung ương - ảnh hưởng toàn thị trường
    'fed': 3, 'fomc': 3, 'interest rate': 3, 'rate cut': 3, 'rate hike': 3,
    'cpi': 3, 'inflation': 2, 'powell': 2, 'jerome powell': 2, 'recession': 2,
    # Pháp lý / Quản lý nhà nước - rủi ro hệ thống
    'sec': 3, 'lawsuit': 2, 'regulation': 2, 'regulator': 2, 'ban ': 3,
    'approve': 2, 'approval': 2, 'reject': 2, 'court': 2, 'doj': 2, 'cftc': 2,
    # ETF / Dòng vốn tổ chức
    'etf': 3, 'blackrock': 2, 'inflow': 2, 'outflow': 2, 'institutional': 1,
    # Sự cố / Bảo mật - ảnh hưởng tức thời, mạnh
    'hack': 3, 'exploit': 3, 'breach': 3, 'stolen': 3, 'bankruptcy': 3,
    'collapse': 3, 'insolvent': 3, 'liquidation': 2, 'exit scam': 3,
    # Sàn giao dịch lớn
    'binance': 1, 'coinbase': 1, 'okx': 1, 'exchange': 1, 'delist': 2, 'listing': 1,
    # Sự kiện on-chain / cấu trúc thị trường lớn
    'halving': 2, 'fork': 1, 'upgrade': 1, 'whale': 1,
}

CRYPTO_QUERY_TERMS = ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'blockchain']


class NewsEngine:
    """Thu thập, chấm điểm quan trọng và dịch tin tức thị trường sang tiếng Việt"""

    def __init__(self):
        self.news_cache = []
        self.last_update = None
        self.economic_calendar = []

    def _score_importance(self, title: str, description: str) -> int:
        """Chấm điểm mức độ quan trọng của 1 tin dựa trên từ khóa"""
        text = f"{title} {description}".lower()
        score = 0
        for keyword, weight in IMPORTANCE_KEYWORDS.items():
            if keyword in text:
                score += weight
        return score

    async def _translate_to_vi(self, text: str) -> str:
        """Dịch văn bản sang tiếng Việt bằng endpoint dịch miễn phí (không cần API key).
        Nếu dịch lỗi (mất mạng, bị chặn...) sẽ trả về nguyên văn tiếng Anh, không làm gãy luồng."""
        if not text:
            return text
        try:
            url = "https://translate.googleapis.com/translate_a/single"
            params = {
                'client': 'gtx', 'sl': 'en', 'tl': 'vi', 'dt': 't', 'q': text[:900]
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=6.0)) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        translated = "".join(seg[0] for seg in data[0] if seg[0])
                        return translated
        except Exception as e:
            logger.debug(f"Translate failed, fallback to original text: {e}")
        return text

    async def _fetch_rss_feed(self, source_name: str, url: str) -> List[Dict]:
        """Lấy tin từ 1 nguồn RSS công khai"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10.0)) as response:
                    if response.status != 200:
                        return []
                    raw = await response.text()

            parsed = feedparser.parse(raw)
            news = []
            for entry in parsed.entries[:20]:
                title = entry.get('title', '')
                description = re.sub('<[^<]+?>', '', entry.get('summary', ''))[:300]
                published = entry.get('published_parsed') or entry.get('updated_parsed')
                if published:
                    published_at = datetime(*published[:6]).isoformat()
                else:
                    published_at = datetime.now().isoformat()

                news.append({
                    'title': title,
                    'description': description,
                    'url': entry.get('link', '#'),
                    'published_at': published_at,
                    'source': source_name,
                    'category': 'crypto'
                })
            return news
        except Exception as e:
            logger.error(f"Error fetching RSS feed {source_name}: {e}")
            return []

    async def fetch_crypto_news(self) -> List[Dict]:
        """Lấy tin tức Crypto - ưu tiên RSS công khai (không cần key),
        cộng thêm NewsAPI nếu có key (tùy chọn)"""
        try:
            news = []

            # RSS công khai - nguồn chính, luôn hoạt động không cần key
            rss_results = await asyncio.gather(
                *[self._fetch_rss_feed(name, url) for name, url in RSS_FEEDS.items()],
                return_exceptions=True
            )
            for result in rss_results:
                if isinstance(result, list):
                    news.extend(result)

            # NewsAPI - chỉ dùng thêm nếu người dùng có cấu hình key (tùy chọn, không bắt buộc)
            if NEWS_API_KEY:
                try:
                    url = f"https://newsapi.org/v2/everything?q=cryptocurrency+OR+bitcoin+OR+ethereum&apiKey={NEWS_API_KEY}&language=en&sortBy=publishedAt&pageSize=10"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10.0)) as response:
                            if response.status == 200:
                                data = await response.json()
                                for article in data.get('articles', []):
                                    news.append({
                                        'title': article.get('title'),
                                        'description': article.get('description') or '',
                                        'url': article.get('url'),
                                        'published_at': article.get('publishedAt'),
                                        'source': article.get('source', {}).get('name'),
                                        'category': 'crypto'
                                    })
                except Exception as e:
                    logger.error(f"Error fetching NewsAPI crypto news: {e}")

            logger.info(f"Fetched {len(news)} crypto news articles (RSS + optional NewsAPI)")
            return news
        except Exception as e:
            logger.error(f"Error fetching crypto news: {e}")
            return []

    async def fetch_forex_news(self) -> List[Dict]:
        """Lấy tin tức Forex/vĩ mô - chỉ dùng NewsAPI nếu có key, vì các nguồn RSS chính
        ở trên đã tập trung vào Crypto (bao gồm cả tin vĩ mô ảnh hưởng Crypto)."""
        news = []
        if NEWS_API_KEY:
            try:
                url = f"https://newsapi.org/v2/everything?q=forex+OR+federal+reserve+OR+economy&apiKey={NEWS_API_KEY}&language=en&sortBy=publishedAt&pageSize=10"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10.0)) as response:
                        if response.status == 200:
                            data = await response.json()
                            for article in data.get('articles', []):
                                news.append({
                                    'title': article.get('title'),
                                    'description': article.get('description') or '',
                                    'url': article.get('url'),
                                    'published_at': article.get('publishedAt'),
                                    'source': article.get('source', {}).get('name'),
                                    'category': 'forex'
                                })
            except Exception as e:
                logger.error(f"Error fetching forex news: {e}")
        return news

    async def fetch_economic_calendar(self) -> List[Dict]:
        """Lấy lịch kinh tế vĩ mô (FOMC chính xác 100% + CPI/NFP ước tính) - không cần API key"""
        try:
            from core.economic_calendar import get_upcoming_macro_events
            calendar = get_upcoming_macro_events(limit=5)
            self.economic_calendar = calendar
            logger.info(f"Fetched {len(calendar)} economic calendar events")
            return calendar
        except Exception as e:
            logger.error(f"Error fetching economic calendar: {e}")
            return []

    async def get_fear_greed_index(self) -> Optional[Dict]:
        """Lấy chỉ số Fear & Greed từ Alternative.me (miễn phí, không cần key)"""
        try:
            url = "https://api.alternative.me/fng/"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10.0)) as response:
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
        return None

    async def get_btc_dominance(self) -> Optional[Dict]:
        """Lấy BTC Dominance từ CoinGecko API (miễn phí, không cần key)"""
        try:
            url = "https://api.coingecko.com/api/v3/global"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10.0)) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('data'):
                            market_data = data['data']
                            return {
                                'btc_dominance': market_data.get('market_cap_percentage', {}).get('btc', 0),
                                'total_market_cap': market_data.get('total_market_cap', {}).get('usd', 0),
                                'total_volume': market_data.get('total_volume', {}).get('usd', 0),
                                'timestamp': datetime.now().isoformat()
                            }
        except Exception as e:
            logger.error(f"Error fetching BTC dominance: {e}")
        return None

    async def update_news(self):
        """Cập nhật tin tức mới"""
        try:
            crypto_news = await self.fetch_crypto_news()
            forex_news = await self.fetch_forex_news()

            all_news = crypto_news + forex_news
            all_news.sort(key=lambda x: x.get('published_at', ''), reverse=True)

            self.news_cache = all_news[:60]
            self.last_update = datetime.now()

            logger.info(f"Updated news cache: {len(self.news_cache)} articles")
        except Exception as e:
            logger.error(f"Error updating news: {e}")

    async def get_important_news(self, hours: int = 48, min_score: int = 2, limit: int = 8) -> List[Dict]:
        """Lọc ra những tin QUAN TRỌNG (có khả năng ảnh hưởng giá) trong X giờ qua,
        sắp xếp theo mức độ quan trọng giảm dần, rồi theo thời gian mới nhất."""
        try:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            scored_news = []

            for news in self.news_cache:
                published_at = news.get('published_at')
                pub_time = None
                if published_at:
                    try:
                        pub_time = datetime.fromisoformat(published_at.replace('Z', '+00:00')).replace(tzinfo=None)
                    except Exception:
                        pub_time = None

                if pub_time and pub_time < cutoff_time:
                    continue

                score = self._score_importance(news.get('title', ''), news.get('description', ''))
                if score >= min_score:
                    news_copy = dict(news)
                    news_copy['importance_score'] = score
                    scored_news.append(news_copy)

            scored_news.sort(key=lambda x: (x['importance_score'], x.get('published_at', '')), reverse=True)
            return scored_news[:limit]
        except Exception as e:
            logger.error(f"Error getting important news: {e}")
            return []

    async def get_news_summary(self) -> str:
        """Lấy tóm tắt tin tức QUAN TRỌNG nhất, đã dịch sang tiếng Việt, kèm Fear&Greed
        và lịch sự kiện vĩ mô sắp tới (FOMC/CPI/NFP)."""
        try:
            if not self.news_cache:
                await self.update_news()
            if not self.economic_calendar:
                await self.fetch_economic_calendar()

            important_news = await self.get_important_news(hours=48, min_score=2, limit=6)
            fear_greed = await self.get_fear_greed_index()

            summary = "📰 <b>TIN TỨC QUAN TRỌNG (48h qua)</b>\n"
            summary += "<i>Chỉ hiển thị tin có khả năng ảnh hưởng thị trường</i>\n\n"

            if important_news:
                # Dịch song song để nhanh hơn
                translated_titles = await asyncio.gather(
                    *[self._translate_to_vi(n['title']) for n in important_news]
                )
                for news, vi_title in zip(important_news, translated_titles):
                    stars = "🔥" * min(3, max(1, news['importance_score'] // 3))
                    summary += f"{stars} <b>{vi_title}</b>\n"
                    summary += f"   Nguồn: {news.get('source', 'N/A')}\n\n"
            else:
                summary += "Hiện chưa có tin nào đủ quan trọng trong 48h qua.\n\n"

            if fear_greed:
                emoji = "😱" if fear_greed['value'] < 25 else ("😰" if fear_greed['value'] < 45 else ("😐" if fear_greed['value'] < 55 else ("😏" if fear_greed['value'] < 75 else "🤑")))
                classification_vi = {
                    'Extreme Fear': 'Cực kỳ sợ hãi', 'Fear': 'Sợ hãi', 'Neutral': 'Trung lập',
                    'Greed': 'Tham lam', 'Extreme Greed': 'Cực kỳ tham lam'
                }.get(fear_greed['classification'], fear_greed['classification'])
                summary += f"{emoji} <b>Chỉ số Sợ hãi & Tham lam:</b> {fear_greed['value']}/100 - {classification_vi}\n\n"

            if self.economic_calendar:
                summary += "📅 <b>Sự kiện vĩ mô sắp tới:</b>\n"
                for event in self.economic_calendar[:4]:
                    tag = " (ước tính)" if event.get('is_estimate') else ""
                    summary += f"• <b>{event['event']}</b>{tag}\n"
                    summary += f"  {event['date_display']} - còn {event['days_left']} ngày - Mức độ: {event['importance']}\n"

            return summary
        except Exception as e:
            logger.error(f"Error getting news summary: {e}")
            return "❌ Không thể lấy tin tức lúc này. Vui lòng thử lại sau."


# Singleton instance
news_engine = NewsEngine()
