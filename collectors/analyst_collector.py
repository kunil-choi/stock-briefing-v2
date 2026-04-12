# collectors/analyst_collector.py
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# === 수집 대상 기간 ===
REPORT_DAYS = 1  # 최근 1일 이내 리포트만 수집 (오늘+어제)

# === 네이버 금융 리서치에 리포트를 올리는 증권사 목록 ===
# 네이버 금융에는 아래 증권사들의 리포트가 자동 등록됩니다
BROKERS = [
    "NH투자증권", "삼성증권", "KB증권", "미래에셋증권",
    "한국투자증권", "신한투자증권", "하나증권", "키움증권",
    "대신증권", "메리츠증권", "한화투자증권", "유진투자증권",
    "LS증권", "IBK투자증권", "DB금융투자", "SK증권",
    "현대차증권", "BNK투자증권", "iM증권", "교보증권",
    "다올투자증권", "한양증권", "흥국증권", "리딩투자증권",
    "토스증권", "카카오페이증권",
]


def is_within_days(date_str: str, days: int = REPORT_DAYS) -> bool:
    """날짜 문자열이 최근 N일 이내인지 확인합니다."""
    try:
        # 네이버 금융 날짜 형식: 25.03.04 또는 2025.03.04
        date_str = date_str.strip().replace(" ", "")
        if len(date_str) == 8:  # 25.03.04
            report_date = datetime.strptime(date_str, "%y.%m.%d")
        elif len(date_str) == 10:  # 2025.03.04
            report_date = datetime.strptime(date_str, "%Y.%m.%d")
        else:
            return True  # 파싱 실패하면 일단 포함

        cutoff = datetime.now() - timedelta(days=days)
        return report_date >= cutoff.replace(hour=0, minute=0, second=0)
    except Exception:
        return True  # 파싱 실패하면 일단 포함


def collect_naver_research() -> list:
    """
    네이버 금융 리서치에서 종목분석 리포트를 수집합니다.
    여러 페이지를 순회하며 최근 N일 이내 리포트만 필터링합니다.
    """
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }

    # 종목분석 리포트 - 최대 5페이지까지 순회
    for page in range(1, 6):
        url = f"https://finance.naver.com/research/company_list.naver?&page={page}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.encoding = "euc-kr"
            soup = BeautifulSoup(resp.text, "html.parser")

            rows = soup.select("table.type_1 tr")
            page_has_recent = False

            for row in rows:
                cols = row.select("td")
                if len(cols) >= 5:
                    stock_name = cols[0].get_text(strip=True)
                    title = cols[1].get_text(strip=True)
                    broker = cols[2].get_text(strip=True)
                    date = cols[4].get_text(strip=True)

                    if not stock_name:
                        continue

                    # 날짜 필터링
                    if not is_within_days(date, REPORT_DAYS):
                        continue

                    page_has_recent = True

                    link_tag = cols[1].select_one("a")
                    link = ""
                    if link_tag and link_tag.get("href"):
                        link = "https://finance.naver.com/research/" + link_tag["href"]

                    # 목표가 추출 시도
                    target_price = ""
                    opinion = ""
                    if len(cols) >= 4:
                        price_text = cols[3].get_text(strip=True)
                        if price_text:
                            target_price = price_text

                    results.append({
                        "source_type": "애널리스트",
                        "source_name": broker,
                        "title": f"[{stock_name}] {title}",
                        "summary": f"종목: {stock_name} | 증권사: {broker} | 목표가: {target_price} | 날짜: {date}",
                        "link": link,
                        "published": date,
                        "stock_name": stock_name,
                        "broker": broker,
                    })

            # 이 페이지에 최근 리포트가 하나도 없으면 더 이상 넘기지 않음
            if not page_has_recent:
                break

        except Exception as e:
            print(f"  [네이버 리서치 오류] 페이지 {page}: {e}")

    return results


def collect_naver_industry() -> list:
    """
    네이버 금융 리서치에서 산업분석 리포트도 수집합니다.
    섹터/테마 트렌드 파악에 유용합니다.
    """
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }

    for page in range(1, 3):
        url = f"https://finance.naver.com/research/industry_list.naver?&page={page}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.encoding = "euc-kr"
            soup = BeautifulSoup(resp.text, "html.parser")

            rows = soup.select("table.type_1 tr")
            for row in rows:
                cols = row.select("td")
                if len(cols) >= 4:
                    sector = cols[0].get_text(strip=True)
                    title = cols[1].get_text(strip=True)
                    broker = cols[2].get_text(strip=True)
                    date = cols[3].get_text(strip=True)

                    if not sector or not title:
                        continue

                    if not is_within_days(date, REPORT_DAYS):
                        continue

                    link_tag = cols[1].select_one("a")
                    link = ""
                    if link_tag and link_tag.get("href"):
                        link = "https://finance.naver.com/research/" + link_tag["href"]

                    results.append({
                        "source_type": "애널리스트",
                        "source_name": broker,
                        "title": f"[산업] [{sector}] {title}",
                        "summary": f"섹터: {sector} | 증권사: {broker} | 날짜: {date}",
                        "link": link,
                        "published": date,
                    })

        except Exception as e:
            print(f"  [산업분석 오류] 페이지 {page}: {e}")

    return results


def collect_analyst() -> list:
    """모든 애널리스트 소스를 통합 수집합니다."""
    results = []

    print(f"  기간: 최근 {REPORT_DAYS}일 이내")
    print(f"  대상: 네이버 금융 리서치 등록 증권사 {len(BROKERS)}개사")

    # 종목분석 리포트
    print("  종목분석 리포트 수집 중...")
    company_reports = collect_naver_research()
    results.extend(company_reports)
    print(f"    → {len(company_reports)}건")

    # 산업분석 리포트
    print("  산업분석 리포트 수집 중...")
    industry_reports = collect_naver_industry()
    results.extend(industry_reports)
    print(f"    → {len(industry_reports)}건")

    # 수집된 증권사 통계
    brokers_found = set()
    for r in results:
        brokers_found.add(r.get("source_name", ""))
    print(f"  수집된 증권사: {len(brokers_found)}개사 - {', '.join(sorted(brokers_found))}")

    return results
