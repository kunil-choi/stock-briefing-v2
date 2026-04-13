import re
import json
from .api_client import call_claude_with_retry
from .naver_finance import (
    verify_stock_via_naver,
    fetch_naver_stock_price,
    fetch_naver_daily_prices,
    generate_candlestick_base64,
    fetch_naver_company_info,
)

CB = "\u0060\u0060\u0060"


def validate_stocks(data, api_key, all_data=None, stock_map=None):
    print("\n" + "=" * 60)
    print("[검증] 분석 결과 원본 재확인 시작...")
    print("=" * 60)

    _naver_cache = {}

    def _cached_verify(stock_name):
        if stock_name not in _naver_cache:
            _naver_cache[stock_name] = verify_stock_via_naver(stock_name)
        return _naver_cache[stock_name]

    def _get_code(stock_name, naver_result):
        if naver_result and naver_result.get("code"):
            return naver_result["code"]
        if stock_map and stock_name in stock_map:
            return stock_map[stock_name]
        return None

    def name_in_text(stock_name, text):
        n = stock_name.lower().strip()
        t = text.lower()
        if n in t:
            return True
        if n.replace(" ", "") in t.replace(" ", ""):
            return True
        for part in n.split():
            if len(part) >= 2 and part in t:
                return True
        clean = re.sub(r'[()주식회사\s]', '', n)
        if len(clean) >= 2 and clean in t:
            return True
        if len(n) >= 3 and n[:3] in t:
            return True
        return False

    type_aliases = {
        "뉴스": ["뉴스", "news", "rss"],
        "경제방송": ["경제방송", "방송", "broadcast", "경제tv"],
        "유튜브": ["유튜브", "youtube", "유튜버"],
        "애널리스트리포트": ["애널리스트", "리포트", "report", "증권사", "analyst"],
    }

    def match_source_type(type_a, type_b):
        a = type_a.lower()
        b = type_b.lower()
        if a in b or b in a:
            return True
        for key, aliases in type_aliases.items():
            a_match = any(al in a for al in aliases)
            b_match = any(al in b for al in aliases)
            if a_match and b_match:
                return True
        return False

    # ── 검증-A ──
    if all_data:
        print("\n[검증-A] 각 소스별 원본 데이터 재확인...")
        source_pool = {}
        for item in all_data:
            st = item.get("source_type", "기타")
            text = " ".join([
                item.get("title", ""),
                item.get("summary", ""),
                item.get("source_name", ""),
                item.get("content", ""),
            ]).lower()
            if st not in source_pool:
                source_pool[st] = []
            source_pool[st].append(text)

        for stype, texts in source_pool.items():
            print(f"  [DATA] {stype}: {len(texts)}건")

        for stock in data.get("stocks", []):
            name = stock.get("name", "")
            verified_reasons = []
            removed_sources = []
            for reason in stock.get("reasons", []):
                reason_stype = reason.get("source_type", "")
                matched_texts = []
                for pool_stype, pool_texts in source_pool.items():
                    if match_source_type(reason_stype, pool_stype):
                        matched_texts.extend(pool_texts)
                if not matched_texts:
                    verified_reasons.append(reason)
                    continue
                found = any(name_in_text(name, t) for t in matched_texts)
                if found:
                    verified_reasons.append(reason)
                else:
                    removed_sources.append(reason_stype)
            if removed_sources:
                print(
                    f"  [TRIM] {name}: [{', '.join(removed_sources)}] "
                    f"원본에 근거 없음 -> 해당 소스만 제거"
                )
            stock["reasons"] = verified_reasons
            verified_types = list(set(r["source_type"] for r in verified_reasons))
            stock["source_types"] = verified_types
            stock["overlap_count"] = len(verified_types)

            # ✅ 검증-A 후 channel_counts / total_count를 실제 남은 reasons 기준으로 재계산
            new_counts = {"뉴스": 0, "경제방송": 0, "유튜브": 0, "애널리스트": 0}
            for r in verified_reasons:
                st = r.get("source_type", "")
                if st in new_counts:
                    new_counts[st] += 1
            stock["channel_counts"] = new_counts
            stock["total_count"] = sum(new_counts.values())

        before = len(data["stocks"])
        data["stocks"] = [
            s for s in data["stocks"] if len(s.get("reasons", [])) > 0
        ]
        removed = before - len(data["stocks"])
        if removed > 0:
            print(f"  [DEL] 근거 0개 종목 {removed}개 제거")

        data["stocks"].sort(
            key=lambda x: x.get("overlap_count", 0), reverse=True
        )
        for i, stock in enumerate(data["stocks"]):
            stock["rank"] = i + 1
        print(f"[검증-A] 완료: {len(data['stocks'])}개 종목 유지")
    else:
        print("[검증-A] 원본 데이터 없음 -> 스킵")

    # ── 검증-B ──
    print("\n[검증-B] 네이버 금융 종목 확인 및 주가 조회...")
    foreign_keywords = [
        "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "알파벳",
        "아마존", "메타", "넷플릭스", "AMD", "인텔", "퀄컴", "브로드컴",
        "NVIDIA", "Tesla", "Apple", "Microsoft", "Google", "Amazon",
        "Meta", "Netflix", "TSMC", "ASML", "ARM", "팔란티어", "마이크론",
        "코스트코", "월마트", "비자", "마스터카드",
    ]

    for stock in data.get("stocks", []):
        name = stock.get("name", "")
        is_foreign = any(kw in name for kw in foreign_keywords)
        if is_foreign:
            stock["market"] = "해외"
            stock["verified_price"] = None
            stock["chart_base64"] = None
            print(f"  [OK] {name} - 해외 종목")
            continue

        stock["market"] = "국내"
        naver_result = _cached_verify(name)
        code = _get_code(name, naver_result)

        if code:
            stock["naver_code"] = code
            print(f"  [OK] {name} ({code})")
            price_info = fetch_naver_stock_price(name, code_override=code)
            stock["verified_price"] = price_info
            if price_info:
                print(f"  [PRICE] {name}: {price_info['price']}원 {price_info.get('change', '')}")
                daily = fetch_naver_daily_prices(code, days=14)
                if daily:
                    chart_b64 = generate_candlestick_base64(daily, name)
                    stock["chart_base64"] = chart_b64
                    if chart_b64:
                        print(f"  [CHART] {name} 차트 생성 완료 ({len(daily)}일)")
                    else:
                        stock["chart_base64"] = None
                else:
                    stock["chart_base64"] = None
            else:
                stock["verified_price"] = None
                stock["chart_base64"] = None
        else:
            print(f"  [WARN] {name}: 코드 조회 실패 -> 종목 유지, 주가 없음")
            stock["verified_price"] = None
            stock["chart_base64"] = None

    for stock in data.get("hidden_picks", []):
        name = stock.get("name", "")
        is_foreign = any(kw in name for kw in foreign_keywords)
        if is_foreign:
            stock["market"] = "해외"
            stock["verified_price"] = None
            stock["chart_base64"] = None
            continue

        stock["market"] = "국내"
        naver_result = _cached_verify(name)
        code = _get_code(name, naver_result)

        if code:
            stock["naver_code"] = code
            price_info = fetch_naver_stock_price(name, code_override=code)
            stock["verified_price"] = price_info
            if price_info:
                print(f"  [PRICE] {name}: {price_info['price']}원 (히든픽)")
                daily = fetch_naver_daily_prices(code, days=14)
                if daily:
                    chart_b64 = generate_candlestick_base64(daily, name)
                    stock["chart_base64"] = chart_b64
                    if chart_b64:
                        print(f"  [CHART] {name} 차트 생성 완료 (히든픽, {len(daily)}일)")
                    else:
                        stock["chart_base64"] = None
                else:
                    stock["chart_base64"] = None
            else:
                stock["verified_price"] = None
                stock["chart_base64"] = None
        else:
            print(f"  [WARN] {name}: 코드 조회 실패 (히든픽)")
            stock["verified_price"] = None
            stock["chart_base64"] = None

    # ── 검증-C ──
    print("\n[검증-C] 최종 데이터 팩트체크...")
    if data.get("stocks"):
        try:
            company_info_lines = []
            all_stock_list = (
                list(data.get("stocks", []))
                + list(data.get("hidden_picks", []))
            )
            for s in all_stock_list:
                name = s.get("name", "")
                code = s.get("naver_code", "")
                if not code:
                    vp = s.get("verified_price")
                    if vp:
                        code = vp.get("code", "")
                if code:
                    print(f"  [기업정보] {name}({code}) 조회 중...")
                    ci = fetch_naver_company_info(code)
                    if ci.get("sector"):
                        peers_str = (
                            ", ".join(ci["peers"][:5])
                            if ci.get("peers") else "정보없음"
                        )
                        company_info_lines.append(
                            "- " + name + ": 업종=" + ci["sector"]
                            + ", 동종업종기업=[" + peers_str + "]"
                        )
                        print(f"    -> 업종: {ci['sector']}, 동종: {peers_str}")
                    else:
                        print(f"    -> 업종 정보 없음")

            company_block = (
                "\n".join(company_info_lines)
                if company_info_lines else "기업정보 없음"
            )

            price_info_lines = []
            for s in data.get("stocks", []):
                name = s.get("name", "")
                vp = s.get("verified_price")
                if vp:
                    price_info_lines.append(
                        "- " + name + ": " + vp["price"] + "원 ("
                        + vp.get("change", "") + ", "
                        + vp.get("change_pct", "") + ")"
                    )
                elif s.get("market") == "해외":
                    price_info_lines.append("- " + name + ": 해외 종목")
            for s in data.get("hidden_picks", []):
                name = s.get("name", "")
                vp = s.get("verified_price")
                if vp:
                    price_info_lines.append(
                        "- " + name + ": " + vp["price"] + "원 ("
                        + vp.get("change", "") + ", "
                        + vp.get("change_pct", "") + ")"
                    )
            price_block = (
                "\n".join(price_info_lines)
                if price_info_lines else "주가 데이터 없음"
            )

            check_target = json.loads(json.dumps(data, ensure_ascii=False))
            for s in check_target.get("stocks", []):
                s.pop("chart_base64", None)
            for s in check_target.get("hidden_picks", []):
                s.pop("chart_base64", None)
            target_json = json.dumps(check_target, ensure_ascii=False, indent=2)

            fc_prompt = (
                "당신은 한국 주식시장 전문 팩트체커입니다.\n"
                "아래 AI 브리핑 데이터를 읽고, 내용상 사실 오류가 있는지 검토하세요.\n\n"
                "## 검토 항목:\n"
                "1. 기업 설명 오류: 잘못된 업종, 사업 내용, 모회사/자회사 관계 등\n"
                "2. 주가/가격 오류: 실제 주가 데이터와 불일치하는 서술\n"
                "3. 사실관계 오류: 잘못된 수치, 날짜, 인물, 이벤트 등\n"
                "4. 기업의 업종 설명이 아래 '네이버 금융 기업정보'의 업종과 "
                "일치하는지 반드시 확인\n\n"
                "## 네이버 금융 기업정보:\n" + company_block + "\n\n"
                "## 실시간 주가 데이터:\n" + price_block + "\n\n"
                "## 검토 대상 브리핑 데이터:\n"
                + CB + "json\n" + target_json + "\n" + CB + "\n\n"
                "## 응답 규칙:\n"
                "- 오류를 발견하면 해당 부분만 수정하여 전체 JSON을 반환하세요\n"
                "- 오류가 없으면 원본 JSON을 그대로 반환하세요\n"
                "- 종목을 삭제하지 마세요. 내용만 교정하세요\n"
                "- source_url은 절대 변경하지 마세요\n"
                "- channel_counts, total_count, overlap_count, rank는 절대 변경하지 마세요\n"
                "- 반드시 JSON만 반환하세요"
            )

            print("  [API] 팩트체크 Claude 호출...")
            fc_result = call_claude_with_retry(api_key, fc_prompt, max_tokens=16000)
            if fc_result:
                json_match = re.search(r'\{[\s\S]*\}', fc_result)
                if json_match:
                    corrected = json.loads(json_match.group())

                    for orig in data.get("stocks", []):
                        for corr in corrected.get("stocks", []):
                            if corr.get("name") == orig.get("name"):
                                # ✅ 검증-A에서 재계산한 수치 필드 전부 원본으로 강제 복원
                                for key in [
                                    "verified_price", "market", "naver_code",
                                    "chart_base64", "source_types",
                                    "overlap_count", "rank",
                                    "channel_counts", "total_count",
                                ]:
                                    corr[key] = orig.get(key)
                                for i, corr_r in enumerate(corr.get("reasons", [])):
                                    if i < len(orig.get("reasons", [])):
                                        corr_r["source_url"] = orig["reasons"][i].get("source_url", "")

                    for orig in data.get("hidden_picks", []):
                        for corr in corrected.get("hidden_picks", []):
                            if corr.get("name") == orig.get("name"):
                                for key in [
                                    "verified_price", "market",
                                    "naver_code", "chart_base64",
                                ]:
                                    corr[key] = orig.get(key)
                                for i, corr_r in enumerate(corr.get("reasons", [])):
                                    if i < len(orig.get("reasons", [])):
                                        corr_r["source_url"] = orig["reasons"][i].get("source_url", "")

                    old_desc = {s["name"]: s.get("description", "") for s in data.get("stocks", [])}
                    new_desc = {s["name"]: s.get("description", "") for s in corrected.get("stocks", [])}
                    changes = sum(
                        1 for name in old_desc
                        if name in new_desc and old_desc[name] != new_desc[name]
                    )
                    if changes:
                        print(f"[검증-C] {changes}건 교정됨")

                    data["stocks"] = corrected.get("stocks", data["stocks"])
                    data["hidden_picks"] = corrected.get("hidden_picks", data["hidden_picks"])
                    data["market_summary"] = corrected.get("market_summary", data["market_summary"])
                    data["investment_strategy"] = corrected.get(
                        "investment_strategy", data.get("investment_strategy", "")
                    )
                    print("[검증-C] 완료")
                else:
                    print("[검증-C] JSON 파싱 실패 -> 원본 유지")
            else:
                print("[검증-C] API 응답 없음 -> 원본 유지")
        except Exception as e:
            print(f"[검증-C] 오류: {e} -> 원본 유지")
    else:
        print("[검증-C] 종목 없음 -> 스킵")

    print("\n" + "=" * 60)
    print(f"[검증 완료] 최종 종목 {len(data.get('stocks', []))}개, "
          f"히든픽 {len(data.get('hidden_picks', []))}개")
    print("=" * 60)
    return data
