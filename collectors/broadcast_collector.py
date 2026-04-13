# collectors/broadcast_collector.py
#
# ⚠️  이 파일은 현재 main.py에서 import되지 않으므로 실행되지 않습니다.
#     경제방송 수집은 collectors/youtube_collector.py 의
#     collect_broadcast_youtube() 함수가 담당합니다.
#
#     향후 웹사이트 직접 크롤링이 필요할 경우 이 파일을 활성화하고
#     main.py에 아래를 추가하세요:
#         from collectors.broadcast_collector import collect_broadcast
#         broadcast_web_data = collect_broadcast(channels)
#         all_data.extend(broadcast_web_data)

import requests
from bs4 import BeautifulSoup


def collect_broadcast(sources: dict) -> list:
    """
    경제방송 웹사이트에서 오늘의 주요 종목 관련 기사/영상 제목을 수집합니다.
    각 방송사별로 크롤링 로직을 커스터마이징합니다.
    현재 미사용 상태 — youtube_collector.py가 대체합니다.
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
            href  = a.get("href", "")
            link  = href if href.startswith("http") else "https://www.wowtv.co.kr" + href
            if not title:
                continue
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
            href  = a.get("href", "")
            link  = href if href.startswith("http") else "https://mbnmoney.mbn.co.kr" + href
            if not title:
                continue
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
