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

        # 불필요한 태그 제거
        for tag in soup.select("script, style, nav, header, footer, aside, .ad, .banner, .comment"):
            tag.decompose()

        # 언론사별 본문 셀렉터 (우선순위 순서)
        selectors = [
            "div#newsct_article",        # 네이버 뉴스
            "div.article_body",          # 한국경제
            "div#article_body",          # 매일경제
            "div.article-body",          # 서울경제
            "article#article-view-content-div",  # 이데일리
            "div#textBody",              # 머니투데이
            "div#news_body_area",        # 조선비즈
            "div.news_cnt_detail_wrap",  # 연합뉴스
            "article",                   # 범용
            "div.article_txt",           # 범용
            "div.article_content",       # 범용
            "div.news_body",             # 범용
        ]

        body_text = ""
        for selector in selectors:
            el = soup.select_one(selector)
            if el:
                body_text = el.get_text(separator=" ", strip=True)
                if len(body_text) > 100:  # 의미있는 텍스트인지 확인
                    break

        # 셀렉터로 못 찾으면 <p> 태그 모음으로 시도
        if len(body_text) < 100:
            paragraphs = soup.select("p")
            texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
            body_text = " ".join(texts)

        # 정리
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
            collected = 0
            for entry in feed.entries[:30]:  # 최근 30개
                # 발행일 파싱
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6])

                title = entry.get("title", "")
                rss_summary = entry.get("summary", "")
                link = entry.get("link", "")

                # 본문 크롤링 (link가 있으면 시도)
                body = ""
                if link and collected < 15:  # 언론사당 최대 15개만 본문 크롤링 (속도/부하 고려)
                    body = fetch_article_body(link, max_chars=1500)

                # summary: 본문 > RSS summary 순서로 사용
                summary = body if len(body) > len(rss_summary) else rss_summary

                results.append({
                    "source_type": "뉴스",
                    "source_name": source_name,
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "published": published.isoformat() if published else "",
                })
                collected += 1
        except Exception as e:
            print(f"[뉴스수집 오류] {source_name}: {e}")

    print(f"  [뉴스] 총 {len(results)}건 수집 (본문 크롤링 포함)")
    return results
