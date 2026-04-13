# analyzer/ai_analyzer.py
import json
import os
import re
from datetime import datetime, timedelta, timezone

from .api_client import call_claude_with_retry
from .validation import validate_stocks
from .html_generator import generate_html

KST = timezone(timedelta(hours=9))
CB = "\u0060\u0060\u0060"


# ──────────────────────────────────────────
# 1단계: 종목 목록 로드 (캐시 활용)
# ──────────────────────────────────────────
def load_stock_names() -> dict:
    """
    네이버 금융에서 코스피/코스닥 전체 종목명 목록을 가져옵니다.
    당일 캐시가 있으면 캐시를 사용하고, 없으면 크롤링 후 저장합니다.
    반환: {종목명: 종목코드}
    """
    import requests
    from bs4 import BeautifulSoup

    cache_path = "data/stock_names_cache.json"
    today = datetime.now(KST).strftime("%Y-%m-%d")

    # 오늘 날짜 캐시가 있으면 바로 사용
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("date") == today and len(cache.get("stocks", {})) > 0:
                print(f"  [종목목록] 캐시 사용 ({len(cache['stocks'])}개, {today})")
                return cache["stocks"]
        except Exception:
            pass

    # 캐시 없으면 크롤링
    print("  [종목목록] 네이버 금융 크롤링 시작...")
    stock_map = {}
    headers = {"User-Agent": "Mozilla/5.0"}

    for market in [0, 1]:
        market_name = "코스피" if market == 0 else "코스닥"
        try:
            # 1페이지로 전체 페이지 수 확인
            url = (f"https://finance.naver.com/sise/sise_market_sum.naver"
                   f"?sosok={market}&page=1")
            res = requests.get(url, headers=headers, timeout=10)
            res.encoding = "euc-kr"
            soup = BeautifulSoup(res.text, "html.parser")

            last_page = 1
            for td in soup.select("table.Nnavi td"):
                a = td.select_one("a")
                if a:
                    try:
                        p = int(a.text.strip())
                        if p > last_page:
                            last_page = p
                    except Exception:
                        pass

            print(f"  [{market_name}] 총 {last_page}페이지 수집 중...")

            for page in range(1, last_page + 1):
                try:
                    page_url = (f"https://finance.naver.com/sise/"
                                f"sise_market_sum.naver"
                                f"?sosok={market}&page={page}")
                    res2 = requests.get(page_url, headers=headers, timeout=10)
                    res2.encoding = "euc-kr"
                    soup2 = BeautifulSoup(res2.text, "html.parser")
                    for row in soup2.select("table.type_2 tr"):
                        link = row.select_one("td.col_name a")
                        if link:
                            name = link.text.strip()
                            href = link.get("href", "")
                            code_match = re.search(r"code=(\d{6})", href)
                            if name and code_match:
                                stock_map[name] = code_match.group(1)
                except Exception:
                    continue

            print(f"  [{market_name}] 완료: 누적 {len(stock_map)}개")

        except Exception as e:
            print(f"  [{market_name}] 오류: {e}")

    # 캐시 저장
    os.makedirs("data", exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"date": today, "stocks": stock_map}, f, ensure_ascii=False)

    print(f"  [종목목록] 총 {len(stock_map)}개 종목 로드 및 캐시 저장")
    return stock_map


# ──────────────────────────────────────────
# 1단계: 종목 추출 (문자열 매칭)
# ──────────────────────────────────────────
def extract_mentions(all_data: list, stock_map: dict) -> dict:
    """
    수집된 텍스트에서 종목명을 문자열 매칭으로 찾아
    채널별 언급 횟수를 카운트합니다.

    반환 형식:
    {
        "삼성전자": {
            "code": "005930",
            "뉴스": [{"source_name": "...", "text": "...", "link": "..."}],
            "경제방송": [...],
            "유튜브": [...],
            "애널리스트": [...],
            "total": 5
        }
    }
    """
    # 소스 타입 정규화
    type_map = {
        "뉴스": "뉴스",
        "경제방송": "경제방송",
        "유튜버": "유튜브",
        "유튜브": "유튜브",
        "애널리스트": "애널리스트",
    }

    # 일반명사와 혼동될 수 있는 짧은 종목명 제외
    skip_names = {
        "삼성", "현대", "LG", "SK", "롯데", "한국", "대한", "국민",
        "신한", "우리", "하나", "기업", "산업", "전자", "화학",
        "건설", "증권", "보험", "카드", "캐피탈", "파이낸스",
        "글로벌", "인터내셔널", "코리아", "홀딩스",
    }

    mentions = {}

    for item in all_data:
        raw_type = item.get("source_type", "기타")
        source_type = type_map.get(raw_type, raw_type)
        source_name = item.get("source_name", "")
        link = item.get("link", "")

        full_text = " ".join([
            item.get("title", ""),
            item.get("summary", ""),
            item.get("content", ""),
        ])

        for stock_name, code in stock_map.items():
            if len(stock_name) < 2 or stock_name in skip_names:
                continue
            if stock_name not in full_text:
                continue

            if stock_name not in mentions:
                mentions[stock_name] = {
                    "code": code,
                    "뉴스": [],
                    "경제방송": [],
                    "유튜브": [],
                    "애널리스트": [],
                    "total": 0,
                }

            # 해당 종목 주변 문맥 150자 추출
            idx = full_text.find(stock_name)
            context = full_text[max(0, idx - 50): idx + 150].strip()

            mentions[stock_name][source_type].append({
                "source_name": source_name,
                "text": context,
                "link": link,
            })
            mentions[stock_name]["total"] += 1

    return mentions


def filter_mentions(mentions: dict, min_channel_types: int = 2) -> dict:
    """
    2개 이상의 서로 다른 채널 종류에서 언급된 종목만 선별합니다.
    총 언급 횟수 기준 내림차순 정렬.
    """
    filtered = {}
    for name, data in mentions.items():
        channel_types = sum(
            1 for t in ["뉴스", "경제방송", "유튜브", "애널리스트"]
            if len(data[t]) > 0
        )
        if channel_types >= min_channel_types:
            filtered[name] = data

    filtered = dict(sorted(
        filtered.items(),
        key=lambda x: x[1]["total"],
        reverse=True
    ))
    print(f"  [필터] {len(filtered)}개 종목 선별 (2개 이상 채널, 총 언급횟수 순)")
    return filtered


# ──────────────────────────────────────────
# 2단계: Claude 심층 분석
# ──────────────────────────────────────────
def build_analysis_prompt(filtered_mentions: dict, all_data: list,
                           today_date: str, now_kst: str) -> str:
    """
    선별된 종목들에 대해 각 채널 녹취록 발언 내용과
    긍정/중립/부정을 분석하는 프롬프트 생성
    """
    # 종목별 관련 원문 텍스트 정리
    stock_contexts = ""
    for rank, (name, data) in enumerate(filtered_mentions.items(), 1):
        if rank > 15:
            break
        stock_contexts += (f"\n\n### [{rank}] {name} "
                           f"(총 {data['total']}회 언급)\n")
        for ch_type in ["뉴스", "경제방송", "유튜브", "애널리스트"]:
            items = data[ch_type]
            if not items:
                continue
            stock_contexts += f"\n**{ch_type} ({len(items)}회):**\n"
            for item in items[:5]:
                stock_contexts += (f"- [{item['source_name']}] "
                                   f"{item['text']}\n")

    # 시장 전체 맥락용 뉴스 헤드라인
    news_headlines = ""
    for item in all_data:
        if item.get("source_type") == "뉴스":
            news_headlines += f"- {item.get('title', '')}\n"

    prompt = (
        f"당신은 한국 주식시장 전문 애널리스트입니다.\n"
        f"기준 시각: {now_kst}\n\n"
        f"아래는 오늘 4개 채널(뉴스/경제방송/유튜브/애널리스트리포트)에서 "
        f"2개 이상 채널에 공통 언급된 종목들과 관련 발언 원문입니다.\n"
        f"각 발언을 꼼꼼히 읽고 분석해주세요.\n\n"
        f"**분석 지침:**\n"
        f"1. 각 발언에서 해당 종목에 대한 평가를 긍정/중립/부정으로 판단하세요.\n"
        f"2. '특정 종목', '이 종목', '이런 종목' 같은 모호한 표현이 있으면 "
        f"앞뒤 문맥을 읽어 실제 어떤 종목을 가리키는지 파악하고 "
        f"반드시 구체적 종목명으로 기재하세요.\n"
        f"3. signal은 긍정/부정/중립 발언 횟수를 합산해 다수결로 결정하세요.\n"
        f"4. channel_counts는 각 채널별 실제 언급 횟수를 그대로 기재하세요.\n"
        f"5. total_count는 모든 채널 언급 횟수의 합계입니다.\n"
        f"6. overlap_count는 언급된 채널 종류의 수입니다 "
        f"(뉴스/경제방송/유튜브/애널리스트 중 1개 이상인 채널 수).\n"
        f"7. reasons에는 채널별 실제 발언 내용을 구체적으로 요약하세요. "
        f"모호한 표현 없이 반드시 종목명을 명시하세요.\n"
        f"8. hidden_picks는 공통 언급 종목 외에 한 채널에서만 언급됐지만 "
        f"투자 가치가 높다고 판단되는 긍정적 종목 최대 3개를 선별하세요.\n"
        f"9. description 200자, price_trend/catalyst/risk 각 150자, "
        f"reasons detail 각 100자.\n"
        f"10. market_summary는 오늘 시장의 핵심 이슈 3가지를 "
        f"'소제목: 설명' 형식으로 각 300자씩 작성하세요.\n"
        f"11. final_summary는 시장 전망과 구체적 투자 전략을 400자로 작성하세요.\n"
        f"12. 절대로 '특정 종목', '특정 주식', '이 종목' 같은 모호한 표현을 "
        f"사용하지 마세요.\n\n"
        f"## 오늘 뉴스 헤드라인 (시장 맥락):\n{news_headlines}\n\n"
        f"## 종목별 채널 발언 원문:\n{stock_contexts}\n\n"
        f"JSON만 출력하세요:\n\n"
        + CB + "json\n"
        "{\n"
        f'  "briefing_date": "{today_date}",\n'
        '  "market_summary": "이슈1 소제목: 설명\\n\\n이슈2 소제목: 설명\\n\\n이슈3 소제목: 설명",\n'
        '  "hot_sectors": ["섹터1", "섹터2", "섹터3"],\n'
        '  "stocks": [\n'
        "    {\n"
        '      "rank": 1,\n'
        '      "name": "종목명",\n'
        '      "signal": "긍정",\n'
        '      "description": "기업 소개 200자",\n'
        '      "price_trend": "주가흐름 150자",\n'
        '      "catalyst": "상승촉매 150자",\n'
        '      "risk": "리스크 150자",\n'
        '      "total_count": 5,\n'
        '      "channel_counts": {"뉴스": 1, "경제방송": 1, "유튜브": 3, "애널리스트": 0},\n'
        '      "source_types": ["뉴스", "경제방송", "유튜브"],\n'
        '      "overlap_count": 3,\n'
        '      "reasons": [\n'
        '        {"source_type": "뉴스", "source_name": "출처명", '
        '"source_url": "https://...", "detail": "발언 내용 100자"},\n'
        '        {"source_type": "경제방송", "source_name": "채널명", '
        '"source_url": "https://...", "detail": "발언 내용 100자"},\n'
        '        {"source_type": "유튜브", "source_name": "채널명", '
        '"source_url": "https://...", "detail": "발언 내용 100자"}\n'
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "hidden_picks": [\n'
        "    {\n"
        '      "rank": 1,\n'
        '      "name": "종목명",\n'
        '      "signal": "긍정",\n'
        '      "description": "기업 소개 300자",\n'
        '      "catalyst": "주목 이유 150자",\n'
        '      "risk": "리스크 150자",\n'
        '      "reasons": [\n'
        '        {"source_type": "유튜브", "source_name": "채널명", '
        '"source_url": "https://...", "detail": "발언 내용 100자"}\n'
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "final_summary": "시장 전망 + 투자 전략 400자"\n'
        "}\n"
        + CB
    )
    return prompt


# ──────────────────────────────────────────
# 메인 함수
# ──────────────────────────────────────────
def analyze_and_generate_html(all_data, api_key, channels_data=None, gh_repo=""):
    print("\n" + "=" * 60)
    print("[AI 분석] 시작 (종목추출 → 심층분석 → 검증 → HTML)")
    print("=" * 60)

    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    today_date = datetime.now(KST).strftime("%Y-%m-%d")

    # ── 1단계: 코드로 종목 추출 ──
    print("\n[1단계] 종목명 추출 (네이버 종목목록 매칭)...")
    stock_map = load_stock_names()

    if not stock_map:
        print("[1단계] 종목 목록 로드 실패 -> 폴백")
        data = {
            "briefing_date": today_date,
            "market_summary": "종목 목록 로드에 실패했습니다. 잠시 후 다시 시도해주세요.",
            "hot_sectors": [],
            "stocks": [],
            "hidden_picks": [],
            "final_summary": "데이터 수집은 완료되었으나 종목 목록 로드에 실패했습니다.",
        }
        html = generate_html(data, channels_data, gh_repo)
        return html

    mentions = extract_mentions(all_data, stock_map)
    print(f"  [추출] 언급 종목 총 {len(mentions)}개 발견")

    filtered = filter_mentions(mentions, min_channel_types=2)

    if not filtered:
        print("[1단계] 공통 언급 종목 없음 -> 폴백")
        data = {
            "briefing_date": today_date,
            "market_summary": "오늘 수집된 데이터에서 공통 언급 종목을 찾지 못했습니다.",
            "hot_sectors": [],
            "stocks": [],
            "hidden_picks": [],
            "final_summary": "데이터 수집은 완료되었으나 분석할 종목이 없습니다.",
        }
        html = generate_html(data, channels_data, gh_repo)
        return html

    # ── 2단계: Claude 심층 분석 ──
    print(f"\n[2단계] Claude 심층 분석 ({len(filtered)}개 종목)...")
    prompt = build_analysis_prompt(filtered, all_data, today_date, now_kst)
    result_text = call_claude_with_retry(api_key, prompt, max_tokens=16000)

    data = None
    if result_text:
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if json_match:
            try:
                data = json.loads(json_match.group())
                print(f"[2단계] 파싱 성공: "
                      f"종목 {len(data.get('stocks', []))}개, "
                      f"히든픽 {len(data.get('hidden_picks', []))}개")
            except json.JSONDecodeError as e:
                print(f"[2단계] JSON 파싱 실패: {e}")

    if not data:
        print("[2단계] 폴백 데이터 사용")
        data = {
            "briefing_date": today_date,
            "market_summary": "AI 분석 중 일시적 오류가 발생했습니다.",
            "hot_sectors": [],
            "stocks": [],
            "hidden_picks": [],
            "final_summary": "데이터 수집은 완료되었으나 AI 분석에 실패했습니다.",
        }

    # ── 검증 (검증-B/C 유지, 검증-D 제거) ──
    if data.get("stocks") or data.get("hidden_picks"):
        data = validate_stocks(data, api_key, all_data)
    else:
        print("[검증] 종목 없음 -> 스킵")

    # ── 저장 ──
    os.makedirs("data", exist_ok=True)
    save_data = json.loads(json.dumps(data, ensure_ascii=False))
    for s in save_data.get("stocks", []):
        s.pop("chart_base64", None)
    for s in save_data.get("hidden_picks", []):
        s.pop("chart_base64", None)
    with open("data/briefing_data.json", "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print("[저장] data/briefing_data.json 완료")

    html = generate_html(data, channels_data, gh_repo)
    return html
