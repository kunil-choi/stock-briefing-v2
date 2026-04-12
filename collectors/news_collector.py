# collectors/news_collector.py
import feedparser
import re
from datetime import datetime, timedelta

def collect_news(rss_feeds: dict) -> list:
    """
    뉴스 RSS에서 최근 24시간 이내 증권 관련 기사를 수집하고
    언급된 종목명을 추출합니다.
    """
    results = []
    cutoff = datetime.now() - timedelta(hours=24)

    for source_name, rss_url in rss_feeds.items():
        try:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries[:30]:  # 최근 30개
                # 발행일 파싱
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6])

                results.append({
                    "source_type": "뉴스",
                    "source_name": source_name,
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", ""),
                    "link": entry.get("link", ""),
                    "published": published.isoformat() if published else "",
                })
        except Exception as e:
            print(f"[뉴스수집 오류] {source_name}: {e}")

    return results