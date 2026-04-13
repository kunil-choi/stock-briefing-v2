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
# 1단계: 코드로 종목명 추출 (Claude 호출 없음)
# ──────────────────────────────────────────
def load_stock_names() -> dict:
    """
    네이버 금융에서 코스피/코스닥 전체 종목명 목록을 가져옵니다.
    {종목명: 종목코드} 딕셔너리 반환
    """
    import requests
    stock_map = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    markets = [
        "https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page=",  # 코스피
        "https://finance.naver.com/sise/sise_market_sum.naver?sosok=1&page=",  # 코스닥
    ]
    for base_url in markets:
        for page in range(1, 30):
            try:
                url = base_url + str(page)
                res = requests.get(url, headers=headers, timeout=10)
                res.encoding = "euc-kr"
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(res.text, "html.parser")
                rows = soup.select("table.type_2 tr")
                found = 0
                for row in rows:
                    link = row.select_one("td.col_name a")
                    if link:
                        name = link.text.strip()
                        href = link.get("href", "")
                        code_match = re.search(r"code=(\d{6})", href)
                        if name and code_match:
                            stock_map[name] = code_match.group(1)
                            found += 1
                if found == 0:
                    break
            except Exception:
                break
    print(f"  [종목목록] 총 {len(stock_map)}개 종목 로드")
    return stock_map


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
        },
        ...
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

    mentions = {}

    # 짧은 종목명(1글자) 제외, 일반명사와 혼동되는 단어 제외
    skip_names = {"삼성", "현대", "LG", "SK", "롯데", "한국", "대한", "국민", "신한", "우리",
                  "하나", "기업", "산업", "전자", "화학", "건설", "증권", "보험", "카드"}

    for item in all_data:
        raw_type = item.get("source_type", "기타")
        source_type = type_map.get(raw_type, raw_type)
        source_name = item.get("source_name", "")
        link = item.get("link", "")

        # 제목 + 자막/본문 합쳐서 검색
        full_text = " ".join([
            item.get("title", ""),
            item.get("summary", ""),
            item.get("content", ""),
        ])

        for stock_name, code in stock_map.items():
            if len(stock_name) < 2 or stock_name in skip_names:
                continue
            if stock_name in full_text:
                if stock_name not in mentions:
                    mentions[stock_name] = {
                        "code": code,
                        "뉴스": [],
                        "경제방송": [],
                        "유튜브": [],
                        "애널리스트": [],
                        "total": 0,
                    }
                # 해당 종목 주변 문맥 100자 추출
                idx = full_text.find(stock_name)
                context = full_text[max(0, idx - 50): idx + 100].strip()

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
    """
    filtered = {}
    for name, data in mentions.items():
        channel_types = sum(1 for t in ["뉴스", "경제방송", "유튜브", "애널리스트"]
                           if len(data[t]) > 0)
        if channel_types >= min_channel_types:
            filtered[name] = data

    # 총 언급 횟수 기준 내림차순 정렬
    filtered = dict(sorted(filtered.items(),
                           key=lambda x: x[1]["total"], reverse=True))
    print(f"  [필터] {len(filtered)}개 종목 선별 "
          f"(2개 이상 채널 언급, 총 언급 횟수 순)")
    return filtered


# ──────────────────────────────────────────
# 2단계: Claude로 심층 분석
# ──────────────────────────────────────────
def build_analysis_prompt(filtered_mentions: dict, all_data: list,
                           today_date: str, now_kst: str) -> str:
    """
    선별된 종목들에 대해 각 채널 녹취록에서
    발언 내용과 긍정/중립/부정을 분석하는 프롬프트 생성
    """
    # 종목별 관련 원문 텍스트 정리
    stock_contexts = ""
    for rank, (name, data) in enumerate(filtered_mentions.items(), 1):
        if rank > 15:  # 최대 15개 종목만
            break
        stock_contexts += f"\n\n### [{rank}] {name} (총 {data['total']}회 언급)\n"
        for ch_type in ["뉴스", "경제방송", "유튜브", "애널리스트"]:
            items = data[ch_type]
            if not items:
                continue
            stock_contexts += f"\n**{ch_type} ({len(items)}회):**\n"
            for item in items[:5]:  # 채널별 최대 5개
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
        f"2개 이상 채널에 공통 언급된 종목들과 관련 발언입니다.\n"
        f"각 종목에 대한 발언을 꼼꼼히 읽고 분석해주세요.\n\n"
        f"**중요 지침:**\n"
        f"1. 각 발언에서 해당 종목에 대한 평가(긍정/중립/부정)를 판단하세요.\n"
        f"2. '특정 종목', '이 종목', '이런 종목' 같은 모호한 표현이 있으면 "
        f"앞뒤 문맥을 읽어 실제 어떤 종목을 가리키는지 파악하세요.\n"
        f"3. signal은 긍정/부정/중립 발언 횟수를 합산해 다수결로 결정하세요.\n"
        f"4. 채널별 언급 횟수(뉴스/경제방송/유튜브/애널리스트)를 그대로 기재하세요.\n"
        f"5. total_count는 모든 채널 언급 횟수의 합계입니다.\n"
        f"6. reasons에는 채널별 실제 발언 내용을 요약해서 기재하세요.\n"
        f"7. 발언 내용을 요약할 때 '특정 종목' 같은 모호한 표현을 "
        f"절대 사용하지 말고 반드시 구체적 종목명을 쓰세요.\n"
        f"8. description은 기업 소개 200자, price_trend/catalyst/risk는 각 150자.\n"
        f"9. market_summary는 오늘 시장에서 가장 중요한 이슈 3가지를 "
        f"'소제목: 설명' 형식으로 300자씩 작성하세요.\n"
        f"10. final_summary는 시장 전망과 투자 전략을 400자로 작성하세요.\n\n"
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
        '      "signal": "긍정/부정/중립 중 하나",\n'
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
        '"source_url": "https://...", "detail": "발언 내용 요약 100자"},\n'
        '        {"source_type": "유튜브", "source_name": "채널명", '
        '"source_url": "https://...", "detail": "발언 내용 요약 100자"}\n'
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
        '"source_url": "https://...", "detail": "발언 내용 요약 100자"}\n'
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
    mentions = extract_mentions(all_data, stock_map)
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

    # ── 검증 (검증-D 제거, 검증-B/C 유지) ──
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
