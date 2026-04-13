import json
import os
import re
from datetime import datetime, timedelta, timezone

from .api_client import call_claude_with_retry
from .validation import validate_stocks
from .html_generator import generate_html

try:
    from config import PANEL_PASSWORD
except ImportError:
    PANEL_PASSWORD = "stock2026!"

KST = timezone(timedelta(hours=9))
CB = "\u0060\u0060\u0060"


def analyze_and_generate_html(all_data, api_key, channels_data=None, gh_repo=""):
    print("\n" + "=" * 60)
    print("[AI 분석] 시작 (1차 분석 -> 검증 -> HTML)")
    print("=" * 60)

    grouped = {}
    for item in all_data:
        st = item.get("source_type", "기타")
        if st not in grouped:
            grouped[st] = []
        grouped[st].append(item)

    data_sections = ""
    for stype, items in grouped.items():
        data_sections += "\n\n## [" + stype + "] (" + str(len(items)) + "건)\n"
        for item in items[:50]:
            title = item.get("title", "")
            summary = item.get("summary", "")
            source = item.get("source_name", "")
            link = item.get("link", "")
            data_sections += "- [" + source + "] " + title
            if summary:
                data_sections += " | " + summary
            if link:
                data_sections += " | URL: " + link
            data_sections += "\n"

    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    today_date = datetime.now(KST).strftime("%Y-%m-%d")

    prompt = ("당신은 한국 주식시장 전문 애널리스트입니다.\n"
        "아래는 " + now_kst + " 기준으로 4개 채널(뉴스, 경제방송, 유튜브, 애널리스트리포트)에서 수집된 데이터입니다.\n\n"
        + data_sections + "\n\n"
        "위 데이터를 분석하여 아래 JSON 형식으로 응답해주세요.\n\n"
        "**중요 지침:**\n"
        "1. market_summary: 투자에 영향을 주는 가장 중요한 이슈 3가지를 선정하세요. 각 이슈는 \"소제목: 설명\" 형식으로, 설명은 300자 분량으로 작성하세요. 이슈 사이는 \\n\\n으로 구분하세요.\n"
        "2. stocks: 관심 종목 최대 10개. 반드시 2개 이상의 서로 다른 채널(뉴스/경제방송/유튜브/애널리스트리포트)에서 언급된 종목만 포함하세요. 1개 채널에서만 언급된 종목은 stocks에 넣지 마세요. 겹침이 많은 순서대로 정렬하세요.\n"
        "3. hidden_picks: 히든 종목 최대 3개. 투자 가치가 있다고 판단되는 긍정적 종목만 포함하세요. 중립이나 부정적 종목은 제외합니다. hidden_picks의 signal은 항상 \"긍정\"으로 설정하세요.\n"
        "4. signal은 반드시 \"긍정\", \"부정\", \"중립\" 중 하나로 표시하세요.\n"
        "5. stocks의 description(종목요약)은 해당 기업의 주력 사업, 시장 지위, 최근 실적 동향 등을 포함하여 200자 내외로 작성하세요.\n"
        "6. price_trend(주가흐름), catalyst(상승촉매), risk(리스크)는 각각 150자 내외로 작성하세요.\n"
        "7. hidden_picks의 description은 해당 기업이 어떤 회사인지, 주력 사업이 무엇인지, 시장에서의 위치, 최근 동향 등을 구체적으로 설명하여 300자 내외로 작성하세요.\n"
        "8. reasons의 각 detail은 100자 내외로 해당 채널에서 언급된 내용을 충실하게 설명하세요.\n"
        "9. reasons의 source_type은 반드시 \"뉴스\", \"경제방송\", \"유튜브\", \"애널리스트리포트\" 중 하나여야 합니다.\n"
        "10. reasons에 source_url 필드를 포함하세요. 원본 데이터에 URL이 있으면 해당 URL을, 없으면 빈 문자열을 넣으세요.\n"
        "11. final_summary(AI 최종 요약)는 시장 전망과 함께 구체적인 투자 전략 조언(업종 배분, 매매 타이밍, 리스크 관리 등)을 포함하여 400자 내외로 작성하세요.\n"
        "12. 뉴스 데이터를 반드시 적극 반영하세요. 뉴스에서 언급된 종목, 이슈, 시장 동향을 다른 채널(유튜브, 경제방송 등)과 교차 검증하여 분석에 포함하세요.\n"
        "13. 각 종목의 reasons에 뉴스 출처가 있으면 반드시 포함하세요. source_type은 \"뉴스\"로, source_name은 해당 언론사명으로, source_url은 기사 URL로 기재하세요.\n"
        "14. market_summary 작성 시 뉴스 기사의 팩트(수치, 정책, 이벤트 등)를 우선적으로 활용하세요. 뉴스는 가장 신뢰도 높은 1차 소스입니다.\n"
        "15. 절대로 '특정 종목', '특정 주식', '특정 기업', '한 종목', '일부 종목' 같은 모호한 표현을 사용하지 마세요. 원본 데이터에서 언급된 실제 종목명(예: SK하이닉스, 두산에너빌리티 등)을 반드시 그대로 기재하세요. 원본에서 종목명을 확인할 수 없는 경우에만 '미공개 종목'이라고 표기하고, 그 외에는 반드시 구체적 종목명을 적으세요.\n\n"
        "JSON만 출력하고 다른 텍스트는 포함하지 마세요.\n\n"
        + CB + "json\n"
        "{\n"
        '  "briefing_date": "' + today_date + '",\n'
        '  "market_summary": "이슈1 소제목: 이슈1 상세 설명(300자)\\n\\n이슈2 소제목: 이슈2 상세 설명(300자)\\n\\n이슈3 소제목: 이슈3 상세 설명(300자)",\n'
        '  "hot_sectors": ["섹터1", "섹터2", "섹터3"],\n'
        '  "stocks": [\n'
        "    {\n"
        '      "rank": 1,\n'
        '      "name": "종목명",\n'
        '      "signal": "긍정/부정/중립 중 하나",\n'
        '      "description": "기업 소개와 종목요약 200자 내외",\n'
        '      "price_trend": "주가흐름 150자 내외",\n'
        '      "catalyst": "상승촉매 150자 내외",\n'
        '      "risk": "리스크 150자 내외",\n'
        '      "overlap_count": 3,\n'
        '      "source_types": ["뉴스", "유튜브", "애널리스트리포트"],\n'
        '      "reasons": [\n'
        '        {"source_type": "뉴스", "source_name": "출처명", "source_url": "https://...", "detail": "100자 내외 충실한 설명"},\n'
        '        {"source_type": "유튜브", "source_name": "채널명", "source_url": "https://...", "detail": "100자 내외 충실한 설명"},\n'
        '        {"source_type": "애널리스트리포트", "source_name": "증권사명", "source_url": "", "detail": "100자 내외 충실한 설명"}\n'
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "hidden_picks": [\n'
        "    {\n"
        '      "rank": 1,\n'
        '      "name": "종목명",\n'
        '      "signal": "긍정",\n'
        '      "description": "기업 소개, 주력 사업, 시장 위치, 최근 동향 등 300자 내외 구체적 설명",\n'
        '      "catalyst": "주목 이유 150자 내외",\n'
        '      "risk": "리스크 150자 내외",\n'
        '      "reasons": [\n'
        '        {"source_type": "유튜브", "source_name": "채널명", "source_url": "https://...", "detail": "100자 내외 충실한 설명"}\n'
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "final_summary": "시장 전망 + 투자 전략 조언 400자 내외"\n'
        "}\n"
        + CB)

    print("\n[1차 분석] Claude API 호출...")
    result_text = call_claude_with_retry(api_key, prompt, max_tokens=16000)

    data = None
    if result_text:
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if json_match:
            try:
                data = json.loads(json_match.group())
                stock_count = len(data.get("stocks", []))
                hidden_count = len(data.get("hidden_picks", []))
                print(f"[1차 분석] 파싱 성공: 종목 {stock_count}개, 히든픽 {hidden_count}개")
            except json.JSONDecodeError as e:
                print(f"[1차 분석] JSON 파싱 실패: {e}")

    if not data:
        print("[1차 분석] 폴백 데이터 사용")
        data = {
            "briefing_date": today_date,
            "market_summary": "AI 분석 중 일시적 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            "hot_sectors": [],
            "stocks": [],
            "hidden_picks": [],
            "final_summary": "데이터 수집은 완료되었으나 AI 분석에 실패했습니다.",
        }

    if data.get("stocks") or data.get("hidden_picks"):
        data = validate_stocks(data, api_key, all_data)
    else:
        print("[검증] 분석된 종목이 없어 검증을 건너뜁니다.")

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
