# config.py
import os
import json

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
GH_TOKEN = os.getenv("GH_TOKEN", "")

# GitHub 저장소 정보
GITHUB_REPO = "kunil-choi/stock-briefing"
CHANNELS_FILE = "channels.json"

# 채널 관리 패널 비밀번호
PANEL_PASSWORD = "stock2026!"

# === 뉴스 RSS ===
NEWS_RSS_FEEDS = {
    "한국경제": "https://www.hankyung.com/feed/stock",
    "매일경제": "https://www.mk.co.kr/rss/30100041/",
    "연합뉴스 경제": "https://www.yna.co.kr/rss/economy.xml",
    "이데일리": "https://rss.edaily.co.kr/edaily_stock.xml",
    "머니투데이": "https://rss.mt.co.kr/mt_stock.xml",
}

# === 인기 패널 목록 (최근 1개월 내 3회 이상 출연) ===
POPULAR_PANELISTS = [
    "홍춘욱", "오건영", "박세익", "김학균", "이효석",
    "정용진", "강방천", "이채원", "최준철", "김경필",
    "염승환", "이선엽", "곽상준", "박문환", "허재환",
    "서영수", "김한진", "이경민", "김일구", "전종규",
    "이주열", "박종훈", "김현석", "신중호", "이창용",
]

# === 애널리스트 리포트 ===
ANALYST_SOURCES = [
    "https://finance.naver.com/research/company_list.naver",
    "https://finance.naver.com/research/industry_list.naver",
]

# 수집 시간 설정
BROADCAST_HOURS = 24
YOUTUBER_HOURS = 24
REPORT_DAYS = 1

# KRX 종목 리스트
KRX_STOCK_LIST_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"


def load_channels():
    """channels.json에서 채널 목록을 로드 (broadcast, youtuber, top50)"""
    try:
        with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 필수 카테고리가 없으면 빈 딕셔너리로 초기화
            for cat in ["broadcast", "youtuber", "top50"]:
                if cat not in data:
                    data[cat] = {}
            return data
    except FileNotFoundError:
        print(f"[config] {CHANNELS_FILE} 파일을 찾을 수 없습니다. 빈 채널 목록을 사용합니다.")
        return {"broadcast": {}, "youtuber": {}, "top50": {}}
