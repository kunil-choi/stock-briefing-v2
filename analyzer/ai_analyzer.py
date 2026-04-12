import anthropic
import json
import os
import re
import io
import base64
import time
import requests
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

try:
    from config import PANEL_PASSWORD
except ImportError:
    PANEL_PASSWORD = "stock2026!"

KST = timezone(timedelta(hours=9))
CB = "\u0060\u0060\u0060"

CLAUDE_MODELS = [
    "claude-sonnet-4-20250514",
    "claude-3-7-sonnet-20250219",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-haiku-20240307",
]


def call_claude_with_retry(api_key, prompt, max_tokens=16000, max_retries=5):
    client = anthropic.Anthropic(api_key=api_key)
    for model in CLAUDE_MODELS:
        for attempt in range(max_retries):
            try:
                print(f"  [API] 모델={model}, 시도={attempt+1}/{max_retries}")
                response = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}]
                )
                result = response.content[0].text.strip()
                print(f"  [API] 성공 (모델={model}, {len(result)}자)")
                return result
            except anthropic.APIStatusError as e:
                status = e.status_code
                if status in (529, 503, 500):
                    wait = min(30 * (attempt + 1), 120)
                    print(f"  [API] {status} 서버 과부하 - {wait}초 대기...")
                    time.sleep(wait)
                    continue
                elif status == 429:
                    print(f"  [API] 429 속도제한 - 60초 대기...")
                    time.sleep(60)
                    continue
                else:
                    print(f"  [API] HTTP {status} 오류: {e.message}")
                    break
            except Exception as e:
                print(f"  [API] 예외: {e}")
                if attempt < max_retries - 1:
                    time.sleep(10)
                    continue
                break
        print(f"  [API] 모델 {model} 실패 -> 다음 모델 시도")
    print("  [API] 모든 모델/재시도 실패")
    return ""


def verify_stock_via_naver(stock_name):
    try:
        search_url = "https://finance.naver.com/search/searchList.naver?query=" + requests.utils.quote(stock_name)
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(search_url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        first_link = soup.select_one("table.tbl_search td.tit a")
        if first_link:
            href = first_link.get("href", "")
            code_match = re.search(r"code=(\d{6})", href)
            found_name = first_link.text.strip()
            if code_match:
                return {"name": found_name, "code": code_match.group(1)}
    except Exception as e:
        print("  [네이버검색] " + stock_name + " 검색 실패: " + str(e))
    return None


def fetch_naver_stock_price(stock_name, code_override=None):
    code = code_override
    if not code:
        result = verify_stock_via_naver(stock_name)
        if result:
            code = result["code"]
    if not code:
        return None
    try:
        url = "https://finance.naver.com/item/main.naver?code=" + code
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        price_el = soup.select_one("#chart_area > div.rate_info > div > p.no_today > em > span.blind")
        price = price_el.text.strip() if price_el else None
        blind_spans = soup.select("#chart_area > div.rate_info > div > p.no_exday > em > span.blind")
        change = blind_spans[0].text.strip() if len(blind_spans) > 0 else None
        change_pct = blind_spans[1].text.strip() if len(blind_spans) > 1 else None
        no_exday = soup.select_one("#chart_area > div.rate_info > div > p.no_exday")
        is_down = False
        if no_exday:
            em = no_exday.select_one("em")
            if em and "nv01" in em.get("class", []):
                is_down = True
        if change:
            change = ("-" if is_down else "+") + change
        if change_pct:
            change_pct = ("-" if is_down else "+") + change_pct
        if price:
            return {"price": price, "change": change or "", "change_pct": change_pct or "", "code": code}
    except Exception as e:
        print("  [네이버] " + stock_name + "(" + code + ") 주가 조회 실패: " + str(e))
    return None


def fetch_naver_daily_prices(code, days=14):
    import pandas as pd
    try:
        url = "https://finance.naver.com/item/sise_day.naver?code=" + code
        headers = {"User-Agent": "Mozilla/5.0"}
        all_rows = []
        for page in range(1, 4):
            page_url = url + "&page=" + str(page)
            html = requests.get(page_url, headers=headers, timeout=10).text
            dfs = pd.read_html(io.StringIO(html))
            if dfs:
                df = dfs[0].dropna(how="all")
                all_rows.append(df)
            if len(all_rows) > 0 and len(pd.concat(all_rows).dropna(how="all")) >= days:
                break
        if not all_rows:
            return []
        df = pd.concat(all_rows).dropna(how="all").reset_index(drop=True)
        results = []
        for _, row in df.iterrows():
            try:
                date_str = str(row.iloc[0]).strip()
                close = int(float(str(row.iloc[1]).replace(",", "").strip()))
                open_p = int(float(str(row.iloc[3]).replace(",", "").strip()))
                high = int(float(str(row.iloc[4]).replace(",", "").strip()))
                low = int(float(str(row.iloc[5]).replace(",", "").strip()))
                volume = int(float(str(row.iloc[6]).replace(",", "").strip()))
                results.append({"date": date_str, "open": open_p, "high": high, "low": low, "close": close, "volume": volume})
            except (ValueError, IndexError):
                continue
        results = results[:days]
        results.reverse()
        return results
    except Exception as e:
        print("  [차트] " + code + " 일별 시세 조회 실패: " + str(e))
        return []


def generate_candlestick_base64(daily_data, stock_name):
    try:
        import mplfinance as mpf
        import pandas as pd
        import matplotlib
        matplotlib.use("Agg")
        if not daily_data or len(daily_data) < 3:
            return None
        df = pd.DataFrame(daily_data)
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}, inplace=True)
        df = df[["Open", "High", "Low", "Close", "Volume"]]
        mc = mpf.make_marketcolors(up="#ff6b6b", down="#339af0", edge={"up": "#ff6b6b", "down": "#339af0"}, wick={"up": "#ff6b6b", "down": "#339af0"}, volume={"up": "#ff6b6b80", "down": "#339af080"})
        style = mpf.make_mpf_style(marketcolors=mc, facecolor="#141420", edgecolor="#2a2a3e", gridcolor="#1e1e2e", gridstyle="--", rc={"axes.labelcolor": "#888", "xtick.color": "#666", "ytick.color": "#666", "font.size": 8})
        buf = io.BytesIO()
        mpf.plot(df, type="candle", style=style, volume=True, title="\n" + stock_name, ylabel="", ylabel_lower="", figsize=(5, 2.8), tight_layout=True, savefig=dict(fname=buf, dpi=130, bbox_inches="tight", facecolor="#141420", edgecolor="none"))
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode("utf-8")
        buf.close()
        return b64
    except ImportError:
        print("  [차트] mplfinance 미설치 - 차트 생성 건너뜀")
        return None
    except Exception as e:
        print("  [차트] " + stock_name + " 차트 생성 실패: " + str(e))
        return None


def fetch_naver_company_info(code):
    info = {"sector": "", "peers": []}
    try:
        url = "https://finance.naver.com/item/main.naver?code=" + code
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        upjong_links = soup.select('a[href*="sise_group_detail.naver?type=upjong"]')
        for link in upjong_links:
            txt = link.text.strip()
            if txt and len(txt) >= 2:
                info["sector"] = txt
                break
        peer_table = soup.select_one('table[summary*="동종업종비교"]')
        if peer_table:
            peer_links = peer_table.select('a[href*="code="]')
            for pl in peer_links:
                pname = pl.text.strip().replace("*", "").strip()
                if pname and len(pname) >= 2:
                    info["peers"].append(pname)
        if not info["peers"]:
            alt_links = soup.select('div.tab_con1 a[href*="code="]')
            for al in alt_links:
                aname = al.text.strip().replace("*", "").strip()
                if aname and len(aname) >= 2 and aname not in info["peers"]:
                    info["peers"].append(aname)
    except Exception as e:
        print("  [기업정보] " + code + " 조회 실패: " + str(e))
    return info


def validate_stocks(data, api_key, all_data=None):
    print("\n" + "=" * 60)
    print("[검증] 분석 결과 원본 재확인 시작...")
    print("=" * 60)

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

    if all_data:
        print("\n[검증-A] 각 소스별 원본 데이터 재확인...")
        source_pool = {}
        for item in all_data:
            st = item.get("source_type", "기타")
            text = " ".join([item.get("title", ""), item.get("summary", ""), item.get("source_name", ""), item.get("content", "")]).lower()
            if st not in source_pool:
                source_pool[st] = []
            source_pool[st].append(text)
        for stype, texts in source_pool.items():
            print("  [DATA] " + stype + ": " + str(len(texts)) + "건")
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
                    print("  [KEEP] " + name + ": " + reason_stype + " 원본 데이터 없음 -> 유지")
                    verified_reasons.append(reason)
                    continue
                found = any(name_in_text(name, t) for t in matched_texts)
                if found:
                    verified_reasons.append(reason)
                else:
                    removed_sources.append(reason_stype)
            if removed_sources:
                print("  [TRIM] " + name + ": [" + ", ".join(removed_sources) + "] 원본에 근거 없음 -> 해당 소스만 제거")
            stock["reasons"] = verified_reasons
            verified_types = list(set(r["source_type"] for r in verified_reasons))
            stock["source_types"] = verified_types
            stock["overlap_count"] = len(verified_types)
        before = len(data["stocks"])
        data["stocks"] = [s for s in data["stocks"] if len(s.get("reasons", [])) > 0]
        removed = before - len(data["stocks"])
        if removed > 0:
            print("  [DEL] 근거 0개 종목 " + str(removed) + "개 제거")
        data["stocks"].sort(key=lambda x: x.get("overlap_count", 0), reverse=True)
        for i, stock in enumerate(data["stocks"]):
            stock["rank"] = i + 1
        print("[검증-A] 완료: " + str(len(data["stocks"])) + "개 종목 유지")
    else:
        print("[검증-A] 원본 데이터 없음 -> 스킵")

    print("\n[검증-B] 네이버 금융 종목 확인 및 주가 조회...")
    foreign_keywords = ["엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "알파벳", "아마존", "메타", "넷플릭스", "AMD", "인텔", "퀄컴", "브로드컴", "NVIDIA", "Tesla", "Apple", "Microsoft", "Google", "Amazon", "Meta", "Netflix", "TSMC", "ASML", "ARM", "팔란티어", "마이크론", "코스트코", "월마트", "비자", "마스터카드"]
    for stock in data.get("stocks", []):
        name = stock.get("name", "")
        is_foreign = any(kw in name for kw in foreign_keywords)
        if is_foreign:
            stock["market"] = "해외"
            stock["verified_price"] = None
            stock["chart_base64"] = None
            print("  [OK] " + name + " - 해외 종목")
            continue
        stock["market"] = "국내"
        naver_result = verify_stock_via_naver(name)
        if naver_result:
            stock["naver_code"] = naver_result["code"]
            print("  [OK] " + name + " (" + naver_result["code"] + ")")
            price_info = fetch_naver_stock_price(name, code_override=naver_result["code"])
            stock["verified_price"] = price_info
            if price_info:
                print("  [PRICE] " + name + ": " + price_info["price"] + "원 " + price_info.get("change", ""))
                daily = fetch_naver_daily_prices(naver_result["code"], days=14)
                if daily:
                    chart_b64 = generate_candlestick_base64(daily, name)
                    stock["chart_base64"] = chart_b64
                    if chart_b64:
                        print("  [CHART] " + name + " 차트 생성 완료 (" + str(len(daily)) + "일)")
                    else:
                        stock["chart_base64"] = None
                else:
                    stock["chart_base64"] = None
            else:
                stock["verified_price"] = None
                stock["chart_base64"] = None
        else:
            print("  [WARN] " + name + ": 네이버 검색 실패 -> 종목 유지, 주가 없음")
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
        naver_result = verify_stock_via_naver(name)
        if naver_result:
            stock["naver_code"] = naver_result.get("code", "")
            price_info = fetch_naver_stock_price(name, code_override=naver_result["code"])
            stock["verified_price"] = price_info
            stock["chart_base64"] = None
        else:
            stock["verified_price"] = None
            stock["chart_base64"] = None

    print("\n[검증-C] 최종 데이터 팩트체크...")
    if data.get("stocks"):
        try:
            company_info_lines = []
            all_stock_list = list(data.get("stocks", []))
            all_stock_list.extend(data.get("hidden_picks", []))
            for s in all_stock_list:
                name = s.get("name", "")
                code = s.get("naver_code", "")
                if not code:
                    vp = s.get("verified_price")
                    if vp:
                        code = vp.get("code", "")
                if code:
                    print("  [기업정보] " + name + "(" + code + ") 조회 중...")
                    ci = fetch_naver_company_info(code)
                    if ci.get("sector"):
                        peers_str = ", ".join(ci["peers"][:5]) if ci.get("peers") else "정보없음"
                        line = "- " + name + ": 업종=" + ci["sector"] + ", 동종업종기업=[" + peers_str + "]"
                        company_info_lines.append(line)
                        print("    -> 업종: " + ci["sector"] + ", 동종: " + peers_str)
                    else:
                        print("    -> 업종 정보 없음")
            company_block = "\n".join(company_info_lines) if company_info_lines else "기업정보 없음"
            price_info_lines = []
            for s in data.get("stocks", []):
                name = s.get("name", "")
                vp = s.get("verified_price")
                if vp:
                    price_info_lines.append("- " + name + ": " + vp["price"] + "원 (" + vp.get("change","") + ", " + vp.get("change_pct","") + ")")
                elif s.get("market") == "해외":
                    price_info_lines.append("- " + name + ": 해외 종목")
            for s in data.get("hidden_picks", []):
                name = s.get("name", "")
                vp = s.get("verified_price")
                if vp:
                    price_info_lines.append("- " + name + ": " + vp["price"] + "원 (" + vp.get("change","") + ", " + vp.get("change_pct","") + ")")
            price_block = "\n".join(price_info_lines) if price_info_lines else "주가 데이터 없음"
            check_target = json.loads(json.dumps(data, ensure_ascii=False))
            for s in check_target.get("stocks", []):
                s.pop("chart_base64", None)
            for s in check_target.get("hidden_picks", []):
                s.pop("chart_base64", None)
            target_json = json.dumps(check_target, ensure_ascii=False, indent=2)
            fc_prompt = ("당신은 한국 주식시장 전문 팩트체커입니다.\n"
                "아래 AI 브리핑 데이터를 읽고, 내용상 사실 오류가 있는지 검토하세요.\n\n"
                "## 검토 항목:\n"
                "1. 기업 설명 오류: 잘못된 업종, 사업 내용, 모회사/자회사 관계 등\n"
                "2. 주가/가격 오류: 실제 주가 데이터와 불일치하는 서술\n"
                "3. 사실관계 오류: 잘못된 수치, 날짜, 인물, 이벤트 등\n"
                "4. 특히 '자회사', '모회사', '계열사' 등 기업 관계 서술은 엄격하게 검증\n"
                "5. 기업의 업종 설명이 아래 '네이버 금융 기업정보'의 업종과 일치하는지 반드시 확인\n\n"
                "## 네이버 금융 기업정보 (실제 데이터):\n" + company_block + "\n\n"
                "## 실시간 주가 데이터:\n" + price_block + "\n\n"
                "## 검토 대상 브리핑 데이터:\n" + CB + "json\n" + target_json + "\n" + CB + "\n\n"
                "## 응답 규칙:\n"
                "- 기업의 업종이 네이버 금융 기업정보와 다르면 반드시 수정하세요\n"
                "- 예: 네이버에서 '화장품' 업종인데 '전력설비 전문업체'로 적혀있으면 화장품/뷰티 기업으로 교정\n"
                "- 오류를 발견하면 해당 부분만 수정하여 전체 JSON을 반환하세요\n"
                "- 오류가 없으면 원본 JSON을 그대로 반환하세요\n"
                "- 종목을 삭제하지 마세요. 내용만 교정하세요\n"
                "- 반드시 JSON만 반환하세요")
            print("  [API] 팩트체크 Claude 호출...")
            fc_result = call_claude_with_retry(api_key, fc_prompt, max_tokens=16000)
            if fc_result:
                json_match = re.search(r'\{[\s\S]*\}', fc_result)
                if json_match:
                    corrected = json.loads(json_match.group())
                    for orig in data.get("stocks", []):
                        for corr in corrected.get("stocks", []):
                            if corr.get("name") == orig.get("name"):
                                for key in ["verified_price","market","naver_code","chart_base64","source_types","overlap_count","rank"]:
                                    if orig.get(key) is not None:
                                        corr[key] = orig[key]
                    for orig in data.get("hidden_picks", []):
                        for corr in corrected.get("hidden_picks", []):
                            if corr.get("name") == orig.get("name"):
                                for key in ["verified_price","market","naver_code","chart_base64"]:
                                    if orig.get(key) is not None:
                                        corr[key] = orig[key]
                    old_desc = {s["name"]: s.get("description","") for s in data.get("stocks",[])}
                    new_desc = {s["name"]: s.get("description","") for s in corrected.get("stocks",[])}
                    changes = 0
                    for name in old_desc:
                        if name in new_desc and old_desc[name] != new_desc[name]:
                            print("  [수정] " + name + ": 내용 교정됨")
                            changes += 1
                    data["stocks"] = corrected.get("stocks", data["stocks"])
                    data["hidden_picks"] = corrected.get("hidden_picks", data["hidden_picks"])
                    data["market_summary"] = corrected.get("market_summary", data["market_summary"])
                    data["final_summary"] = corrected.get("final_summary", data["final_summary"])
                    print("[검증-C] 완료: " + str(changes) + "건 교정")
                else:
                    print("[검증-C] JSON 파싱 실패 -> 원본 유지")
            else:
                print("[검증-C] API 응답 없음 -> 원본 유지")
        except Exception as e:
            print("[검증-C] 오류: " + str(e) + " -> 원본 유지")
    else:
        print("[검증-C] 종목 없음 -> 스킵")

    print("\n" + "=" * 60)
    total_stocks = len(data.get("stocks", []))
    total_hidden = len(data.get("hidden_picks", []))
    print("[검증 완료] 최종 종목 " + str(total_stocks) + "개, 히든픽 " + str(total_hidden) + "개")
    print("=" * 60)
    return data


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
        "2. stocks: 추천 종목 최대 10개 (여러 채널에서 겹침이 많은 순서대로 정렬)\n"
        "3. hidden_picks: 히든 종목 최대 3개 (소수 채널에서만 언급되었지만 주목할 만한 종목)\n"
        "4. signal은 반드시 \"긍정\", \"부정\", \"중립\" 중 하나로 표시하세요.\n"
        "5. stocks의 description(종목요약)은 해당 기업의 주력 사업, 시장 지위, 최근 실적 동향 등을 포함하여 200자 내외로 작성하세요.\n"
        "6. price_trend(주가흐름), catalyst(상승촉매), risk(리스크)는 각각 150자 내외로 작성하세요.\n"
        "7. hidden_picks의 description은 해당 기업이 어떤 회사인지, 주력 사업이 무엇인지, 시장에서의 위치, 최근 동향 등을 구체적으로 설명하여 300자 내외로 작성하세요.\n"
        "8. reasons의 각 detail은 100자 내외로 해당 채널에서 언급된 내용을 충실하게 설명하세요.\n"
        "9. reasons의 source_type은 반드시 \"뉴스\", \"경제방송\", \"유튜브\", \"애널리스트리포트\" 중 하나여야 합니다.\n"
        "10. reasons에 source_url 필드를 포함하세요. 원본 데이터에 URL이 있으면 해당 URL을, 없으면 빈 문자열을 넣으세요.\n"
        "11. final_summary(AI 최종 요약)는 시장 전망과 함께 구체적인 투자 전략 조언(업종 배분, 매매 타이밍, 리스크 관리 등)을 포함하여 400자 내외로 작성하세요.\n\n"
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
        '      "signal": "긍정/부정/중립 중 하나",\n'
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
                print("[1차 분석] 파싱 성공: 종목 " + str(stock_count) + "개, 히든픽 " + str(hidden_count) + "개")
            except json.JSONDecodeError as e:
                print("[1차 분석] JSON 파싱 실패: " + str(e))

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


def generate_html(data, channels_data=None, gh_repo=""):
    now_kst = datetime.now(KST)
    briefing_date = data.get("briefing_date", now_kst.strftime("%Y-%m-%d"))
    market_summary = data.get("market_summary", "")
    hot_sectors = data.get("hot_sectors", [])
    stocks = data.get("stocks", [])
    hidden_picks = data.get("hidden_picks", [])
    final_summary = data.get("final_summary", "")

    summary_paragraphs = market_summary.split("\n\n")
    formatted_summary = ""
    for para in summary_paragraphs:
        para = para.strip()
        if not para:
            continue
        if ":" in para:
            colon_idx = para.index(":")
            title_part = para[:colon_idx].strip()
            body_part = para[colon_idx+1:].strip()
            formatted_summary += '<div class="summary-block"><h3 class="summary-subtitle">' + title_part + '</h3><p class="summary-text">' + body_part + '</p></div>\n'
        else:
            formatted_summary += '<div class="summary-block"><p class="summary-text">' + para + '</p></div>\n'

    sectors_html = ""
    for sector in hot_sectors:
        sectors_html += '<span class="sector-badge">' + sector + '</span>\n'

    stocks_html = ""
    for stock in stocks:
        name = stock.get("name", "")
        rank = stock.get("rank", "")
        signal = stock.get("signal", "중립")
        description = stock.get("description", "")
        price_trend = stock.get("price_trend", "")
        catalyst = stock.get("catalyst", "")
        risk = stock.get("risk", "")
        overlap = stock.get("overlap_count", 0)
        source_types = stock.get("source_types", [])
        reasons = stock.get("reasons", [])
        verified_price = stock.get("verified_price")
        chart_b64 = stock.get("chart_base64")
        market = stock.get("market", "국내")
        if signal == "긍정":
            signal_class = "signal-positive"
        elif signal == "부정":
            signal_class = "signal-negative"
        else:
            signal_class = "signal-neutral"
        overlap_badge = '<span class="overlap-badge">' + str(overlap) + '개 채널 언급</span>'
        source_tags = ""
        for st in source_types:
            source_tags += '<span class="source-tag">' + st + '</span>'
        price_html = ""
        if verified_price:
            p = verified_price
            change_class = "price-up" if p.get("change", "").startswith("+") else "price-down"
            price_html = ('<div class="price-box">'
                + '<span class="current-price">' + p['price'] + '&#xC6D0;</span>'
                + '<span class="' + change_class + '">' + p.get('change', '') + ' (' + p.get('change_pct', '') + ')</span>'
                + '</div>')
        elif market == "해외":
            price_html = '<div class="price-box"><span class="price-note">해외 종목 (실시간 가격 미제공)</span></div>'
        chart_icon_html = ""
        if chart_b64:
            chart_icon_html = ' <span class="chart-icon" onclick="openChartWindow(\'' + name + '\', \'x\')" data-chart="' + str(rank) + '" title="14일 주가 차트 보기">&#x1F4C8; 주가차트</span>'
        reasons_html = ""
        for reason in reasons:
            rs = reason.get("source_type", "")
            rn = reason.get("source_name", "")
            rd = reason.get("detail", "")
            rurl = reason.get("source_url", "")
            link_html = ""
            if rurl:
                link_html = ' <a href="' + rurl + '" target="_blank" class="source-link" title="원본 보기">&#x1F517; 바로보기</a>'
            reasons_html += ('<div class="reason-item">'
                + '<div class="reason-header">'
                + '<span class="reason-source">[' + rs + '] ' + rn + '</span>' + link_html
                + '</div>'
                + '<p class="reason-detail">' + rd + '</p>'
                + '</div>')
        stocks_html += ('<div class="stock-card">'
            + '<div class="stock-header">'
            + '<span class="stock-rank">#' + str(rank) + '</span>'
            + '<span class="stock-name">' + name + '</span>'
            + '<span class="stock-signal ' + signal_class + '">' + signal + '</span>'
            + overlap_badge
            + '</div>'
            + '<div class="stock-sources">' + source_tags + '</div>'
            + price_html
            + '<div class="stock-info-grid">'
            + '<div class="info-block"><div class="info-label">&#x1F4CB; 종목요약</div><div class="info-text">' + description + '</div></div>'
            + '<div class="info-block"><div class="info-label">&#x1F4C8; 주가흐름</div><div class="info-text">' + price_trend + chart_icon_html + '</div></div>'
            + '<div class="info-block"><div class="info-label">&#x1F680; 상승촉매</div><div class="info-text">' + catalyst + '</div></div>'
            + '<div class="info-block"><div class="info-label">&#x26A0;&#xFE0F; 리스크</div><div class="info-text">' + risk + '</div></div>'
            + '</div>'
            + '<div class="stock-reasons">'
            + '<div class="reasons-title">&#x1F4AC; 채널별 분석 근거</div>'
            + reasons_html
            + '</div>'
            + '</div>')

    hidden_html = ""
    for stock in hidden_picks:
        name = stock.get("name", "")
        rank = stock.get("rank", "")
        signal = stock.get("signal", "중립")
        description = stock.get("description", "")
        catalyst = stock.get("catalyst", "")
        risk = stock.get("risk", "")
        reasons = stock.get("reasons", [])
        verified_price = stock.get("verified_price")
        market = stock.get("market", "국내")
        if signal == "긍정":
            signal_class = "signal-positive"
        elif signal == "부정":
            signal_class = "signal-negative"
        else:
            signal_class = "signal-neutral"
        price_html = ""
        if verified_price:
            p = verified_price
            change_class = "price-up" if p.get("change", "").startswith("+") else "price-down"
            price_html = ('<div class="price-box">'
                + '<span class="current-price">' + p['price'] + '&#xC6D0;</span>'
                + '<span class="' + change_class + '">' + p.get('change', '') + ' (' + p.get('change_pct', '') + ')</span>'
                + '</div>')
        elif market == "해외":
            price_html = '<div class="price-box"><span class="price-note">해외 종목</span></div>'
        reasons_html = ""
        for reason in reasons:
            rs = reason.get("source_type", "")
            rn = reason.get("source_name", "")
            rd = reason.get("detail", "")
            rurl = reason.get("source_url", "")
            link_html = ""
            if rurl:
                link_html = ' <a href="' + rurl + '" target="_blank" class="source-link" title="원본 보기">&#x1F517; 바로보기</a>'
            reasons_html += ('<div class="reason-item">'
                + '<div class="reason-header">'
                + '<span class="reason-source">[' + rs + '] ' + rn + '</span>' + link_html
                + '</div>'
                + '<p class="reason-detail">' + rd + '</p>'
                + '</div>')
        hidden_html += ('<div class="stock-card hidden-card">'
            + '<div class="stock-header">'
            + '<span class="stock-rank hidden-rank">H' + str(rank) + '</span>'
            + '<span class="stock-name">&#x1F48E; ' + name + '</span>'
            + '<span class="stock-signal ' + signal_class + '">' + signal + '</span>'
            + '</div>'
            + price_html
            + '<div class="stock-info-grid">'
            + '<div class="info-block"><div class="info-label">&#x1F3E2; 기업 소개</div><div class="info-text">' + description + '</div></div>'
            + '<div class="info-block"><div class="info-label">&#x1F680; 주목 이유</div><div class="info-text">' + catalyst + '</div></div>'
            + '<div class="info-block"><div class="info-label">&#x26A0;&#xFE0F; 리스크</div><div class="info-text">' + risk + '</div></div>'
            + '</div>'
            + '<div class="stock-reasons">'
            + '<div class="reasons-title">&#x1F4AC; 채널별 분석 근거</div>'
            + reasons_html
            + '</div>'
            + '</div>')

    settings_html = ""
    if channels_data is not None:
        escaped_pw = PANEL_PASSWORD.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
        settings_html = ('<div id="settings-panel" style="display:none; padding:20px; background:#1a1a2e; border-radius:12px; margin-top:20px;">'
            + '<h3 style="color:#e0e0e0;">&#x2699;&#xFE0F; 채널 설정</h3>'
            + '<p style="color:#888;">이 패널에서 데이터 수집 채널을 관리할 수 있습니다.</p>'
            + '<p style="color:#666; font-size:0.85rem;">GitHub: ' + (gh_repo or "미설정") + '</p>'
            + '</div>'
            + '<script>'
            + 'function openSettings() {'
            + 'var pw = prompt("비밀번호를 입력하세요:");'
            + 'if (pw === "' + escaped_pw + '") {'
            + 'document.getElementById("settings-panel").style.display = "block";'
            + '} else if (pw !== null) {'
            + 'alert("비밀번호가 틀렸습니다.");'
            + '}}'
            + '</script>')

    chart_data_js = "var chartData = {};\n"
    for stock in stocks:
        r = stock.get("rank", "")
        b64 = stock.get("chart_base64", "")
        if b64:
            chart_data_js += 'chartData["' + str(r) + '"] = "' + b64 + '";\n'

    # ── 아카이브 링크 생성 ──
    archive_dir = os.path.join("docs", "archive")
    os.makedirs(archive_dir, exist_ok=True)
    archive_links_html = ""
    existing_dates = []
    if os.path.isdir(archive_dir):
        for fname in os.listdir(archive_dir):
            if fname.endswith(".html") and len(fname) == 15:
                d = fname.replace(".html", "")
                existing_dates.append(d)
    existing_dates.append(briefing_date)
    existing_dates = sorted(set(existing_dates), reverse=True)[:7]
    for d in existing_dates:
        if d == briefing_date:
            archive_links_html += '<span class="archive-link archive-today">' + d + ' (오늘)</span>\n'
        else:
            archive_links_html += '<a href="archive/' + d + '.html" class="archive-link">' + d + '</a>\n'

    css_block = """* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0a0a14; color:#e0e0e0; font-family:'Pretendard',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; line-height:1.7; padding:20px; max-width:900px; margin:0 auto; }
.header { text-align:center; padding:30px 0 20px; border-bottom:1px solid #2a2a3e; margin-bottom:30px; }
.header h1 { font-size:1.8rem; color:#ffffff; margin-bottom:6px; }
.header .subtitle { color:#6c5ce7; font-size:0.95rem; margin-bottom:4px; }
.header .date { color:#888; font-size:0.85rem; }
.section { margin-bottom:35px; }
.section-title { font-size:1.3rem; color:#ffffff; margin-bottom:15px; padding-left:12px; border-left:3px solid #6c5ce7; }
.market-summary { background:#141420; border-radius:12px; padding:22px; }
.summary-block { margin-bottom:18px; }
.summary-block:last-child { margin-bottom:0; }
.summary-subtitle { color:#6c5ce7; font-size:1.05rem; margin-bottom:6px; }
.summary-text { color:#ccc; font-size:0.95rem; line-height:1.9; }
.sector-badge { display:inline-block; background:#6c5ce7; color:#fff; padding:5px 14px; border-radius:20px; margin:4px; font-size:0.9rem; }
.stock-card { background:#141420; border-radius:12px; padding:22px; margin-bottom:20px; border:1px solid #2a2a3e; transition:border-color 0.2s; }
.stock-card:hover { border-color:#6c5ce7; }
.hidden-card { border-color:#f39c12; }
.hidden-card:hover { border-color:#e67e22; }
.stock-header { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:12px; }
.stock-rank { background:#6c5ce7; color:#fff; padding:3px 10px; border-radius:8px; font-weight:bold; font-size:0.9rem; }
.hidden-rank { background:#f39c12; }
.stock-name { font-size:1.2rem; font-weight:bold; color:#ffffff; }
.stock-signal { padding:3px 12px; border-radius:8px; font-size:0.85rem; font-weight:bold; }
.signal-positive { background:#ff6b6b33; color:#ff6b6b; }
.signal-negative { background:#339af033; color:#339af0; }
.signal-neutral { background:#ffd93d33; color:#ffd93d; }
.overlap-badge { background:#00b89433; color:#00b894; padding:3px 10px; border-radius:8px; font-size:0.8rem; }
.stock-sources { margin-bottom:10px; }
.source-tag { display:inline-block; background:#2a2a3e; color:#aaa; padding:2px 8px; border-radius:4px; margin:2px; font-size:0.8rem; }
.price-box { background:#1e1e2e; border-radius:8px; padding:10px 15px; margin:10px 0; display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.current-price { font-size:1.1rem; font-weight:bold; color:#fff; }
.price-up { color:#ff6b6b; font-weight:bold; }
.price-down { color:#339af0; font-weight:bold; }
.price-note { color:#888; font-size:0.9rem; }
.stock-info-grid { display:flex; flex-direction:column; gap:14px; margin:15px 0; }
.info-block { background:#1a1a2e; border-radius:8px; padding:14px 16px; }
.info-label { color:#6c5ce7; font-size:0.9rem; font-weight:bold; margin-bottom:6px; display:flex; align-items:center; gap:6px; }
.info-text { color:#ccc; font-size:0.9rem; line-height:1.8; }
.chart-icon { cursor:pointer; font-size:0.85rem; background:#2a2a3e; color:#aaa; padding:3px 10px; border-radius:6px; margin-left:8px; transition:all 0.2s; display:inline-block; }
.chart-icon:hover { background:#6c5ce7; color:#fff; }
.stock-reasons { border-top:1px solid #2a2a3e; padding-top:14px; margin-top:14px; }
.reasons-title { color:#888; font-size:0.85rem; font-weight:bold; margin-bottom:10px; }
.reason-item { background:#1a1a2e; border-radius:8px; padding:12px 14px; margin-bottom:8px; }
.reason-header { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.reason-source { color:#6c5ce7; font-size:0.85rem; font-weight:bold; }
.source-link { color:#00b894; font-size:0.8rem; text-decoration:none; background:#00b89415; padding:2px 8px; border-radius:4px; transition:all 0.2s; }
.source-link:hover { background:#00b89433; color:#fff; }
.reason-detail { color:#bbb; font-size:0.88rem; line-height:1.7; margin-top:4px; }
.final-summary { background:#141420; border-radius:12px; padding:22px; color:#ccc; line-height:1.9; font-size:0.95rem; white-space:pre-line; }
.disclaimer { text-align:center; color:#666; font-size:0.8rem; margin-top:40px; padding:20px; border-top:1px solid #2a2a3e; }
.settings-btn { position:fixed; bottom:20px; right:20px; background:#2a2a3e; color:#888; border:none; padding:8px 14px; border-radius:8px; cursor:pointer; font-size:0.8rem; z-index:100; }
.settings-btn:hover { background:#3a3a4e; color:#fff; }
.archive-section { background:#141420; border-radius:12px; padding:22px; display:flex; flex-wrap:wrap; gap:10px; justify-content:center; }
.archive-link { display:inline-block; background:#2a2a3e; color:#aaa; padding:8px 16px; border-radius:8px; text-decoration:none; font-size:0.9rem; transition:all 0.2s; }
.archive-link:hover { background:#6c5ce7; color:#fff; }
.archive-today { background:#6c5ce7; color:#fff; font-weight:bold; }
@media (max-width:600px) {
    body { padding:12px; }
    .header h1 { font-size:1.4rem; }
    .stock-name { font-size:1rem; }
    .stock-header { gap:6px; }
}"""

    chart_js = ("function openChartWindow(stockName, prefix) {"
        + "var rankEl = event.target.closest('[data-chart]');"
        + "var rank = rankEl ? rankEl.getAttribute('data-chart') : '';"
        + "var b64 = chartData[rank];"
        + "if (!b64) { alert(stockName + ' 차트 데이터가 없습니다.'); return; }"
        + "var win = window.open('', '_blank', 'width=700,height=500,scrollbars=yes');"
        + "win.document.write('<html><head><title>' + stockName + ' - 14일 주가 차트</title>');"
        + "win.document.write('<style>body{background:#0a0a14;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px;}');"
        + "win.document.write('h2{color:#fff;font-family:sans-serif;margin-bottom:15px;}');"
        + "win.document.write('img{max-width:100%;border-radius:10px;box-shadow:0 4px 20px rgba(0,0,0,0.5);}</style></head><body>');"
        + "win.document.write('<h2>' + stockName + ' - 14일 주가 차트</h2>');"
        + "win.document.write('<img src=\"data:image/png;base64,' + b64 + '\" />');"
        + "win.document.write('</body></html>');"
        + "win.document.close(); }")

    no_stocks_msg = '<div class="stock-card"><p style="color:#888; text-align:center;">분석된 추천 종목이 없습니다.</p></div>'
    no_hidden_msg = '<div class="stock-card hidden-card"><p style="color:#888; text-align:center;">분석된 히든픽이 없습니다.</p></div>'
    no_sectors_msg = '<span style="color:#888;">분석된 섹터가 없습니다.</span>'

    full_html = ('<!DOCTYPE html>\n<html lang="ko">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        + '<title>주식 투자 AI 브리핑 - ' + briefing_date + '</title>\n'
        + '<style>\n' + css_block + '\n</style>\n</head>\n<body>\n\n'
        + '<div class="header">\n<h1>&#x1F4CA; 주식 투자 AI 브리핑</h1>\n'
        + '<div class="subtitle">&#x1F4E1; 뉴스 &#xB7; 경제방송 &#xB7; 유튜브 &#xB7; 애널리스트 보고서 분석</div>\n'
        + '<div class="date">' + briefing_date + ' | AI 자동 분석 리포트</div>\n</div>\n\n'
        + '<div class="section">\n<h2 class="section-title">&#x1F30F; 시장 종합 요약</h2>\n'
        + '<div class="market-summary">' + formatted_summary + '</div>\n</div>\n\n'
        + '<div class="section">\n<h2 class="section-title">&#x1F525; 주목 섹터</h2>\n'
        + '<div>' + (sectors_html if sectors_html else no_sectors_msg) + '</div>\n</div>\n\n'
        + '<div class="section">\n<h2 class="section-title">&#x1F3AF; 추천 종목</h2>\n'
        + (stocks_html if stocks_html else no_stocks_msg) + '\n</div>\n\n'
        + '<div class="section">\n<h2 class="section-title">&#x1F48E; 히든픽</h2>\n'
        + (hidden_html if hidden_html else no_hidden_msg) + '\n</div>\n\n'
        + '<div class="section">\n<h2 class="section-title">&#x1F4DD; AI 최종 요약</h2>\n'
        + '<div class="final-summary">' + final_summary + '</div>\n</div>\n\n'
        + '<div class="section">\n<h2 class="section-title">&#x1F4C5; 지난 브리핑</h2>\n'
        + '<div class="archive-section">' + archive_links_html + '</div>\n</div>\n\n'
        + '<div class="disclaimer">\n본 브리핑은 AI가 공개 데이터를 분석한 것으로 투자 권유가 아닙니다.<br>\n'
        + '투자 판단의 책임은 투자자 본인에게 있습니다.\n</div>\n\n'
        + '<button class="settings-btn" onclick="openSettings()">&#x2699;&#xFE0F; 설정</button>\n\n'
        + settings_html + '\n\n'
        + '<script>\n' + chart_data_js + '\n' + chart_js + '\n</script>\n\n'
        + '</body>\n</html>')

    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(full_html)
    print("[HTML] docs/index.html 저장 완료 (" + str(len(full_html)) + "자)")

    # ── 아카이브 사본 저장 ──
    archive_path = os.path.join("docs", "archive", briefing_date + ".html")
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(full_html)
    print("[아카이브] " + archive_path + " 저장 완료")

    # ── 7일 초과 아카이브 정리 ──
    try:
        all_archives = sorted([fn for fn in os.listdir(archive_dir) if fn.endswith(".html")], reverse=True)
        for old_file in all_archives[7:]:
            old_path = os.path.join(archive_dir, old_file)
            os.remove(old_path)
            print("[아카이브] 오래된 파일 삭제: " + old_file)
    except Exception as e:
        print("[아카이브] 정리 중 오류: " + str(e))

    return full_html
