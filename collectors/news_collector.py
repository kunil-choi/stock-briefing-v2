# collectors/news_collector.py
import feedparser
import re
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup


def fetch_article_body(url, max_chars=1500):
    """기사 URL에서 본문 텍스트를 추출합니다 (최대 max_chars자)"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup.select("script, style, nav, header, footer, aside, .ad, .banner, .comment"):
            tag.decompose()

        selectors = [
            "div#newsct_article",
            "div.article_body",
            "div#article_body",
            "div.article-body",
            "article#article-view-content-div",
            "div#textBody",
            "div#news_body_area",
            "div.news_cnt_detail_wrap",
            "article",
            "div.article_txt",
            "div.article_content",
            "div.news_body",
        ]

        body_text = ""
        for selector in selectors:
            el = soup.select_one(selector)
            if el:
                body_text = el.get_text(separator=" ", strip=True)
                if len(body_text) > 100:
                    break

        if len(body_text) < 100:
            paragraphs = soup.select("p")
            texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
            body_text = " ".join(texts)

        body_text = re.sub(r'\s+', ' ', body_text).strip()
        return body_text[:max_chars] if body_text else ""

    except Exception as e:
        print(f"  [본문크롤링] {url[:60]}... 실패: {e}")
        return ""


def collect_news(rss_feeds: dict) -> list:
    """
    뉴스 RSS에서 최근 24시간 이내 증권 관련 기사를 수집하고
    본문을 크롤링하여 풍부한 데이터를 제공합니다.
    """
    results = []
    cutoff = datetime.now() - timedelta(hours=24)

    for source_name, rss_url in rss_feeds.items():
        try:
            feed = feedparser.parse(rss_url)
            # ✅ 수정: 본문 크롤링 전용 카운터를 별도로 관리
            crawl_count = 0

            for entry in feed.entries[:30]:
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6])

                # 24시간 이내 기사만 수집
                if published and published < cutoff:
                    continue

                title = entry.get("title", "")
                rss_summary = entry.get("summary", "")
                link = entry.get("link", "")

                # ✅ 수정: crawl_count로 본문 크롤링 15건 제한을 정확히 제어
                body = ""
                if link and crawl_count < 15:
                    body = fetch_article_body(link, max_chars=1500)
                    crawl_count += 1  # 크롤링 시도 시에만 카운트 증가

                summary = body if len(body) > len(rss_summary) else rss_summary

                results.append({
                    "source_type": "뉴스",
                    "source_name": source_name,
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "published": published.isoformat() if published else "",
                })

        except Exception as e:
            print(f"[뉴스수집 오류] {source_name}: {e}")

    print(f"  [뉴스] 총 {len(results)}건 수집 (본문 크롤링 포함)")
    return results
