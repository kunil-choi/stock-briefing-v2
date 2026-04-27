# analyzer/naver_finance.py
import re
import io
import base64
import requests
from bs4 import BeautifulSoup


def verify_stock_via_naver(stock_name):
    """
    네이버 금융 검색으로 종목명 → 종목코드 조회.
    searchList.naver는 404 폐지됨 → searchResult.naver 로 교체.
    셀렉터도 다중 fallback 적용.
    """
    try:
        search_url = (
            "https://finance.naver.com/search/searchResult.naver?query="
            + requests.utils.quote(stock_name)
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        res = requests.get(search_url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")

        # 셀렉터 우선순위: 새 구조 → 구 구조 순으로 시도
        selectors = [
            "table.tbl_search td.tit a",       # 기존 구조 (혹시 아직 유효하면 재사용)
            "div.section_search a.tit",         # 검색결과 새 구조
            "ul.lst_search li a.tit",           # 리스트형 새 구조
            "div.search_result a[href*='code=']",  # code= 파라미터 포함 링크
            "a[href*='/item/main.naver?code=']",   # 종목 메인 페이지 직접 링크
        ]

        for sel in selectors:
            first_link = soup.select_one(sel)
            if first_link:
                href = first_link.get("href", "")
                code_match = re.search(r"code=(\d{6})", href)
                found_name = first_link.text.strip()
                if code_match and found_name:
                    print(f"  [네이버검색] '{stock_name}' → '{found_name}' ({code_match.group(1)}) [셀렉터: {sel}]")
                    return {"name": found_name, "code": code_match.group(1)}

        print(f"  [네이버검색] '{stock_name}' 검색결과 없음 (셀렉터 매칭 실패)")

    except Exception as e:
        print(f"  [네이버검색] {stock_name} 검색 실패: {e}")
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

        price = None
        price_selectors = [
            "#chart_area > div.rate_info > div > p.no_today > em > span.blind",
            "p.no_today em span.blind",
            "strong#_nowVal",
            "div.rate_info p.no_today em",
        ]
        for sel in price_selectors:
            el = soup.select_one(sel)
            if el:
                price = el.text.strip().replace(",", "").replace("원", "").strip()
                if price and price.isdigit():
                    price = format(int(price), ",")
                    break
                price = el.text.strip()
                if price:
                    break

        change_selectors = [
            "#chart_area > div.rate_info > div > p.no_exday > em > span.blind",
            "p.no_exday em span.blind",
        ]
        blind_spans = []
        for sel in change_selectors:
            blind_spans = soup.select(sel)
            if blind_spans:
                break

        change = blind_spans[0].text.strip() if len(blind_spans) > 0 else None
        change_pct = blind_spans[1].text.strip() if len(blind_spans) > 1 else None

        is_down = False
        no_exday = soup.select_one(
            "#chart_area > div.rate_info > div > p.no_exday"
        ) or soup.select_one("p.no_exday")
        if no_exday:
            em = no_exday.select_one("em")
            if em and "nv01" in em.get("class", []):
                is_down = True

        if change:
            change = ("-" if is_down else "+") + change
        if change_pct:
            change_pct = ("-" if is_down else "+") + change_pct

        if price:
            return {
                "price": price,
                "change": change or "",
                "change_pct": change_pct or "",
                "code": code,
            }
    except Exception as e:
        print(f"  [네이버] {stock_name}({code}) 주가 조회 실패: {e}")
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
            if (
                len(all_rows) > 0
                and len(pd.concat(all_rows).dropna(how="all")) >= days
            ):
                break
        if not all_rows:
            return []
        df = pd.concat(all_rows).dropna(how="all").reset_index(drop=True)
        results = []
        for _, row in df.iterrows():
            try:
                date_str = str(row.iloc[0]).strip()

                # 날짜 형식 유효성 검증 — 숫자와 점(.)으로만 이루어진 날짜만 허용
                if not re.match(r'^\d{4}\.\d{2}\.\d{2}$', date_str):
                    continue

                close_str = str(row.iloc[1]).replace(",", "").strip()
                open_str  = str(row.iloc[3]).replace(",", "").strip()
                high_str  = str(row.iloc[4]).replace(",", "").strip()
                low_str   = str(row.iloc[5]).replace(",", "").strip()
                vol_str   = str(row.iloc[6]).replace(",", "").strip()

                # 각 값이 실제 숫자인지 검증 후 변환
                if not all(v.replace(".", "").isdigit() for v in [close_str, open_str, high_str, low_str, vol_str]):
                    continue

                close  = int(float(close_str))
                open_p = int(float(open_str))
                high   = int(float(high_str))
                low    = int(float(low_str))
                volume = int(float(vol_str))

                results.append({
                    "date": date_str,
                    "open": open_p,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                })
            except (ValueError, IndexError):
                continue

        results = results[:days]
        results.reverse()
        return results
    except Exception as e:
        print(f"  [차트] {code} 일별 시세 조회 실패: {e}")
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
        df.rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }, inplace=True)
        df = df[["Open", "High", "Low", "Close", "Volume"]]

        mc = mpf.make_marketcolors(
            up="#ff6b6b", down="#339af0",
            edge={"up": "#ff6b6b", "down": "#339af0"},
            wick={"up": "#ff6b6b", "down": "#339af0"},
            volume={"up": "#ff6b6b80", "down": "#339af080"},
        )
        style = mpf.make_mpf_style(
            marketcolors=mc,
            facecolor="#141420",
            edgecolor="#2a2a3e",
            gridcolor="#1e1e2e",
            gridstyle="--",
            rc={
                "axes.labelcolor": "#888",
                "xtick.color": "#666",
                "ytick.color": "#666",
                "font.size": 8,
            },
        )

        buf = io.BytesIO()
        mpf.plot(
            df,
            type="candle",
            style=style,
            volume=True,
            title="\n" + stock_name,
            ylabel="",
            ylabel_lower="",
            figsize=(5, 2.8),
            tight_layout=True,
            savefig=dict(
                fname=buf,
                dpi=130,
                bbox_inches="tight",
                facecolor="#141420",
                edgecolor="none",
            ),
        )
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode("utf-8")
        buf.close()
        return b64

    except ImportError:
        print("  [차트] mplfinance 미설치 - 차트 생성 건너뜀")
        return None
    except Exception as e:
        print(f"  [차트] {stock_name} 차트 생성 실패: {e}")
        return None


def fetch_naver_company_info(code):
    info = {"sector": "", "peers": []}
    try:
        url = "https://finance.naver.com/item/main.naver?code=" + code
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")

        upjong_links = soup.select(
            'a[href*="sise_group_detail.naver?type=upjong"]'
        )
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
        print(f"  [기업정보] {code} 조회 실패: {e}")
    return info
