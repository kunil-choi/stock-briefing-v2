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


def load_stock_names() -> dict:
    import requests

    cache_path = "data/stock_names_cache.json"
    today = datetime.now(KST).strftime("%Y-%m-%d")

    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("date") == today and len(cache.get("stocks", {})) > 0:
                print(f"  [종목목록] 캐시 사용 ({len(cache['stocks'])}개, {today})")
                return cache["stocks"]
        except Exception:
            pass

    print("  [종목목록] KRX 종목 목록 로드 중...")
    stock_map = {}
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://data.krx.co.kr/",
    }

    for market_id, market_name in [("STK", "코스피"), ("KSQ", "코스닥")]:
        try:
            url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
            params = {
                "bld": "dbms/MDC/STAT/standard/MDCSTAT01901",
                "mktId": market_id,
                "share": "1",
                "money": "1",
                "csvxls_isNo": "false",
            }
            res = requests.post(url, data=params, headers=headers, timeout=15)
            data = res.json()
            items = data.get("OutBlock_1", [])
            for item in items:
                name = item.get("ISU_ABBRV", "").strip()
                code = item.get("ISU_SRT_CD", "").strip()
                if name and code:
                    stock_map[name] = code
            print(f"  [{market_name}] {len(items)}개 로드")
        except Exception as e:
            print(f"  [{market_name}] KRX 오류: {e}")

    if not stock_map:
        print("  [종목목록] KRX 실패 -> 주요 종목 폴백 사용")
        stock_map = {
            "삼성전자": "005930", "SK하이닉스": "000660", "LG에너지솔루션": "373220",
            "삼성바이오로직스": "207940", "현대차": "005380", "기아": "000270",
            "셀트리온": "068270", "POSCO홀딩스": "005490", "KB금융": "105560",
            "신한지주": "055550", "하나금융지주": "086790", "우리금융지주": "316140",
            "LG화학": "051910", "삼성SDI": "006400", "현대모비스": "012330",
            "카카오": "035720", "NAVER": "035420", "LG전자": "066570",
            "삼성물산": "028260", "SK텔레콤": "017670", "KT": "030200",
            "삼성생명": "032830", "삼성화재": "000810", "메리츠금융지주": "138040",
            "한화에어로스페이스": "012450", "두산에너빌리티": "034020",
            "HD현대중공업": "329180", "HD한국조선해양": "009540",
            "HD현대": "267250", "현대건설": "000720", "GS건설": "006360",
            "대우건설": "047040", "삼성엔지니어링": "028050",
            "SK이노베이션": "096770", "S-Oil": "010950", "GS": "078930",
            "SK": "034730", "LG": "003550", "롯데지주": "004990",
            "CJ": "001040", "한화": "000880", "두산": "000150",
            "LS": "006260", "LS일렉트릭": "010120", "HD현대일렉트릭": "267260",
            "효성중공업": "298040", "LIG넥스원": "079550",
            "한국항공우주": "047810", "현대로템": "064350",
            "한화시스템": "272210", "한화오션": "042660",
            "포스코퓨처엠": "003670", "롯데케미칼": "011170",
            "금호석유": "011780", "한화솔루션": "009830", "OCI홀딩스": "010060",
            "SK가스": "018670", "한국가스공사": "036460", "한국전력": "015760",
            "한국전력기술": "050540", "두산밥캣": "241560", "두산퓨얼셀": "336260",
            "삼성전기": "009150", "삼성SDS": "018260", "삼성증권": "016360",
            "미래에셋증권": "006800", "NH투자증권": "005940", "키움증권": "039490",
            "대신증권": "003540", "메리츠증권": "008560",
            "SK바이오사이언스": "302440", "SK바이오팜": "326030",
            "HLB": "028300", "유한양행": "000100", "종근당": "185750",
            "대웅제약": "069620", "한미약품": "128940", "동아에스티": "170900",
            "녹십자": "006280", "보령": "003850",
            "만도": "204320", "한온시스템": "018880", "현대위아": "011210",
            "하이브": "352820", "SM": "041510", "JYP Ent": "035900",
            "CJ ENM": "035760", "스튜디오드래곤": "253450",
            "엔씨소프트": "036570", "넷마블": "251270",
            "크래프톤": "259960", "카카오게임즈": "293490", "펄어비스": "263750",
            "컴투스": "078340", "위메이드": "112040",
            "에코프로": "086520", "에코프로비엠": "247540",
            "에코프로머티리얼즈": "450080", "엘앤에프": "066970",
            "천보": "278280", "나노신소재": "121600",
            "솔브레인": "357780", "동화기업": "025900",
            "씨에스윈드": "112610", "한솔테크닉스": "004710",
            "이수페타시스": "007660", "원익IPS": "240810",
            "피에스케이": "319660", "HPSP": "403870",
            "레인보우로보틱스": "277810", "두산로보틱스": "454910",
            "HLB생명과학": "067630", "알테오젠": "196170",
            "리가켐바이오": "141080", "오스코텍": "039200",
            "메디톡스": "086900", "클래시스": "214150",
            "루닛": "328130", "뷰노": "338220",
            "카카오페이": "377300", "카카오뱅크": "323410",
            "더존비즈온": "012510", "셀바스AI": "108860",
            "NICE평가정보": "030190", "BGF리테일": "282330",
            "GS리테일": "007070", "이마트": "139480",
            "롯데쇼핑": "023530", "현대백화점": "069960",
            "신세계": "004170", "호텔신라": "008770",
            "파라다이스": "034230", "강원랜드": "035250",
            "CJ대한통운": "000120", "대한항공": "003490",
            "아시아나항공": "020560", "제주항공": "089590",
            "현대글로비스": "086280", "팬오션": "028670",
            "HMM": "011200", "고려아연": "010130",
            "KCC": "002380", "삼성중공업": "010140",
            "포스코인터내셔널": "047050", "LX인터내셔널": "001120",
            "SK에코플랜트": "034300",
            "산일전기": "062040", "LS ELECTRIC": "010120",
        }

    os.makedirs("data", exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"date": today, "stocks": stock_map}, f, ensure_ascii=False)

    print(f"  [종목목록] 총 {len(stock_map)}개 로드 완료")
    return stock_map


def extract_mentions(all_data: list, stock_map: dict) -> dict:
    type_map = {
        "뉴스": "뉴스",
        "경제방송": "경제방송",
        "유튜버": "유튜브",
        "유튜브": "유튜브",
        "애널리스트": "애널리스트",
    }

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
        content_id = link if link else (source_name + "|" + item.get("title", ""))

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

            already = any(
                m.get("content_id") == content_id
                for m in mentions[stock_name][source_type]
            )
            if already:
                continue

            idx = full_text.find(stock_name)
            context = full_text[max(0, idx - 50): idx + 150].strip()

            mentions[stock_name][source_type].append({
                "source_name": source_name,
                "text": context,
                "link": link,
                "content_id": content_id,
            })
            mentions[stock_name]["total"] += 1

    return mentions


def filter_mentions(mentions: dict, min_channel_types: int = 2) -> dict:
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


def build_analysis_prompt(filtered_mentions: dict, all_data: list,
                           today_date: str, now_kst: str) -> str:
    stock_contexts = ""
    for rank, (name, data) in enumerate(filtered_mentions.items(), 1):
        if rank > 15:
            break
        stock_contexts += (
            f"\n\n### [{rank}] {name} (총 {data['total']}회 언급)\n"
        )
        for ch_type in ["뉴스", "경제방송", "유튜브", "애널리스트"]:
            items = data[ch_type]
            if not items:
                continue
            stock_contexts += f"\n**{ch_type} ({len(items)}회):**\n"
            for item in items[:5]:
                link_str = item['link'] if item['link'] else "링크없음"
                stock_contexts += (
                    f"- [{item['source_name']}] (링크: {link_str})\n"
                    f"  {item['text']}\n"
                )

    news_headlines = ""
    for item in all_data:
        if item.get("source_type") == "뉴스":
            news_headlines += f"- {item.get('title', '')}\n"

    prompt = (
        f"당신은 한국 주식시장 전문 애널리스트입니다.\n"
        f"기준 시각: {now_kst}\n\n"
        f"아래는 오늘 4개 채널(뉴스/경제방송/유튜브/애널리스트리포트)에서 "
        f"2개 이상 채널에 공통 언급된 종목들과 관련 발언 원문입니다.\n\n"
        f"**분석 지침:**\n"
        f"1. 각 발언에서 해당 종목에 대한 평가를 긍정/중립/부정으로 판단하세요.\n"
        f"2. signal은 긍정/부정/중립 발언 횟수를 합산해 다수결로 결정하세요.\n"
        f"3. channel_counts는 각 채널별 실제 콘텐츠 수(위 괄호 안 숫자)를 그대로 기재하세요.\n"
        f"4. total_count는 모든 채널 콘텐츠 수의 합계입니다.\n"
        f"5. overlap_count는 언급된 채널 종류의 수입니다.\n"
        f"6. reasons의 source_url은 반드시 위 발언 데이터의 '링크' 값을 그대로 사용하세요. "
        f"링크가 '링크없음'이면 빈 문자열(\"\")로 기재하세요.\n"
        f"7. reasons detail은 채널별 실제 발언 내용을 구체적으로 요약하세요.\n"
        f"8. hidden_picks는 공통 언급 종목 외에 한 채널에서만 언급됐지만 "
        f"투자 가치가 높다고 판단되는 긍정적 종목 최대 3개를 선별하세요.\n"
        f"9. description 200자, price_trend/catalyst/risk 각 150자, "
        f"reasons detail 각 100자.\n"
        f"10. market_summary는 오늘 시장의 핵심 이슈 3가지를 "
        f"'소제목: 설명' 형식으로 각 300자씩 작성하세요.\n"
        f"11. investment_strategy는 시장 요약과 중복되지 않는 "
        f"구체적 투자 전략만 400자로 작성하세요. "
        f"어떤 종목을 언제 어떻게 접근할지 실전적으로 서술하세요.\n"
        f"12. 절대로 '특정 종목', '특정 주식', '이 종목' 같은 모호한 표현을 "
        f"사용하지 마세요.\n\n"
        f"## 오늘 뉴스 헤드라인:\n{news_headlines}\n\n"
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
        '  "investment_strategy": "시장 요약과 중복 없는 구체적 투자 전략 400자"\n'
        "}\n"
        + CB
    )
    return prompt


def _restore_source_url(reason, real_channel_data):
    ch = reason.get("source_type", "")
    sname = reason.get("source_name", "")
    if reason.get("source_url"):
        return

    ch_key = {
        "뉴스": "뉴스", "경제방송": "경제방송",
        "유튜브": "유튜브", "애널리스트": "애널리스트"
    }.get(ch, "")
    if not ch_key or ch_key not in real_channel_data:
        return

    candidates = real_channel_data[ch_key]

    for m in candidates:
        if m.get("source_name") == sname and m.get("link"):
            reason["source_url"] = m["link"]
            return

    for m in candidates:
        real_sname = m.get("source_name", "")
        if (sname in real_sname or real_sname in sname) and m.get("link"):
            reason["source_url"] = m["link"]
            return

    for m in candidates:
        if m.get("link"):
            reason["source_url"] = m["link"]
            return


def analyze_and_generate_html(all_data, api_key, channels_data=None, gh_repo=""):
    print("\n" + "=" * 60)
    print("[AI 분석] 시작 (종목추출 → 심층분석 → 검증 → HTML)")
    print("=" * 60)

    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    today_date = datetime.now(KST).strftime("%Y-%m-%d")

    # ✅ 수정: GH_TOKEN을 환경변수에서 읽어서 generate_html에 전달
    gh_token = os.environ.get("GH_TOKEN", "")

    print("\n[1단계] 종목명 추출 (KRX 종목목록 매칭)...")
    stock_map = load_stock_names()

    if not stock_map:
        data = {
            "briefing_date": today_date,
            "market_summary": "종목 목록 로드에 실패했습니다.",
            "hot_sectors": [],
            "stocks": [],
            "hidden_picks": [],
            "investment_strategy": "데이터 수집은 완료되었으나 종목 목록 로드에 실패했습니다.",
        }
        return generate_html(data, channels_data, gh_repo, gh_token)

    mentions = extract_mentions(all_data, stock_map)
    print(f"  [추출] 언급 종목 총 {len(mentions)}개 발견")

    filtered = filter_mentions(mentions, min_channel_types=2)

    if not filtered:
        data = {
            "briefing_date": today_date,
            "market_summary": "오늘 수집된 데이터에서 공통 언급 종목을 찾지 못했습니다.",
            "hot_sectors": [],
            "stocks": [],
            "hidden_picks": [],
            "investment_strategy": "분석할 종목이 없습니다.",
        }
        return generate_html(data, channels_data, gh_repo, gh_token)

    print(f"\n[2단계] Claude 심층 분석 ({len(filtered)}개 종목)...")
    prompt = build_analysis_prompt(filtered, all_data, today_date, now_kst)
    result_text = call_claude_with_retry(api_key, prompt, max_tokens=16000)

    data = None
    if result_text:
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if json_match:
            try:
                data = json.loads(json_match.group())
                print(
                    f"[2단계] 파싱 성공: "
                    f"종목 {len(data.get('stocks', []))}개, "
                    f"히든픽 {len(data.get('hidden_picks', []))}개"
                )
            except json.JSONDecodeError as e:
                print(f"[2단계] JSON 파싱 실패: {e}")

    if not data:
        data = {
            "briefing_date": today_date,
            "market_summary": "AI 분석 중 일시적 오류가 발생했습니다.",
            "hot_sectors": [],
            "stocks": [],
            "hidden_picks": [],
            "investment_strategy": "AI 분석에 실패했습니다.",
        }

    for stock in data.get("stocks", []):
        name = stock.get("name", "")
        if name in filtered:
            real = filtered[name]
            stock["channel_counts"] = {
                "뉴스": len(real["뉴스"]),
                "경제방송": len(real["경제방송"]),
                "유튜브": len(real["유튜브"]),
                "애널리스트": len(real["애널리스트"]),
            }
            stock["total_count"] = real["total"]
            for reason in stock.get("reasons", []):
                _restore_source_url(reason, real)

    for stock in data.get("hidden_picks", []):
        hp_name = stock.get("name", "")
        for reason in stock.get("reasons", []):
            if reason.get("source_url"):
                continue
            ch_key = {
                "뉴스": "뉴스", "경제방송": "경제방송",
                "유튜브": "유튜브", "애널리스트": "애널리스트"
            }.get(reason.get("source_type", ""), "")
            if not ch_key:
                continue

            if hp_name in filtered:
                _restore_source_url(reason, filtered[hp_name])
                if reason.get("source_url"):
                    continue

            sname = reason.get("source_name", "")
            for stock_data in filtered.values():
                if ch_key not in stock_data:
                    continue
                for m in stock_data[ch_key]:
                    real_sname = m.get("source_name", "")
                    if (sname == real_sname or sname in real_sname or real_sname in sname) and m.get("link"):
                        reason["source_url"] = m["link"]
                        break
                if reason.get("source_url"):
                    break

    if data.get("stocks") or data.get("hidden_picks"):
        data = validate_stocks(data, api_key, all_data, stock_map)
    else:
        print("[검증] 종목 없음 -> 스킵")

    os.makedirs("data", exist_ok=True)
    save_data = json.loads(json.dumps(data, ensure_ascii=False))
    for s in save_data.get("stocks", []):
        s.pop("chart_base64", None)
    for s in save_data.get("hidden_picks", []):
        s.pop("chart_base64", None)
    with open("data/briefing_data.json", "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print("[저장] data/briefing_data.json 완료")

    # ✅ 수정: gh_token을 generate_html에 전달
    return generate_html(data, channels_data, gh_repo, gh_token)
