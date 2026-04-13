import re
import io
import base64
import requests
from bs4 import BeautifulSoup


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
        print(f"  [차트] {stock_name} 차트 생성 실패: {e}")
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
        print(f"  [기업정보] {code} 조회 실패: {e}")
    return info
