# collectors/broadcast_collector.py
import requests
from bs4 import BeautifulSoup

def collect_broadcast(sources: dict) -> list:
    """
    경제방송 웹사이트에서 오늘의 주요 종목 관련 기사/영상 제목을 수집합니다.
    각 방송사별로 크롤링 로직을 커스터마이징합니다.
    """
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }

    # --- 한경TV (wowtv) ---
    try:
        resp = requests.get(
            "https://www.wowtv.co.kr/NewsCenter/News/MainList",
            headers=headers, timeout=10
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        articles = soup.select("a.tit, .article-list a, .news-list a")
        for a in articles[:20]:
            title = a.get_text(strip=True)
            link = a.get("href", "")
            if not link.startswith("http"):
                link = "https://www.wowtv.co.kr" + link
            results.append({
                "source_type": "경제방송",
                "source_name": "한경TV",
                "title": title,
                "summary": "",
                "link": link,
                "published": "",
            })
    except Exception as e:
        print(f"[방송수집 오류] 한경TV: {e}")

    # --- MBN 머니 ---
    try:
        resp = requests.get(
            "https://mbnmoney.mbn.co.kr/",
            headers=headers, timeout=10
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        articles = soup.select(".news_tit a, .article_tit a")
        for a in articles[:20]:
            title = a.get_text(strip=True)
            link = a.get("href", "")
            if not link.startswith("http"):
                link = "https://mbnmoney.mbn.co.kr" + link
            results.append({
                "source_type": "경제방송",
                "source_name": "MBN",
                "title": title,
                "summary": "",
                "link": link,
                "published": "",
            })
    except Exception as e:
        print(f"[방송수집 오류] MBN: {e}")

    return results