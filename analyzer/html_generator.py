import os
import requests
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def generate_html(data, channels_data=None, gh_repo=""):
    now_kst = datetime.now(KST)
    briefing_date = data.get("briefing_date", now_kst.strftime("%Y-%m-%d"))
    briefing_datetime = now_kst.strftime("%Y-%m-%d %H:%M")
    market_summary = data.get("market_summary", "")
    hot_sectors = data.get("hot_sectors", [])
    stocks = data.get("stocks", [])
    hidden_picks = data.get("hidden_picks", [])
    # ✅ final_summary 대신 investment_strategy 사용
    investment_strategy = data.get("investment_strategy", data.get("final_summary", ""))

    stocks = [s for s in stocks if s.get("overlap_count", 0) >= 2]
    hidden_picks = [s for s in hidden_picks if s.get("signal", "") == "긍정"]

    summary_paragraphs = market_summary.split("\n\n")
    formatted_summary = ""
    for para in summary_paragraphs:
        para = para.strip()
        if not para:
            continue
        if ":" in para:
            colon_idx = para.index(":")
            title_part = para[:colon_idx].strip()
            body_part = para[colon_idx + 1:].strip()
            formatted_summary += (
                '<div class="summary-block">'
                '<h3 class="summary-subtitle">' + title_part + '</h3>'
                '<p class="summary-text">' + body_part + '</p>'
                '</div>\n'
            )
        else:
            formatted_summary += (
                '<div class="summary-block">'
                '<p class="summary-text">' + para + '</p>'
                '</div>\n'
            )

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
        naver_code = stock.get("naver_code", "")
        if not naver_code and verified_price:
            naver_code = verified_price.get("code", "")

        if signal == "긍정":
            signal_class = "signal-positive"
        elif signal == "부정":
            signal_class = "signal-negative"
        else:
            signal_class = "signal-neutral"

        channel_counts = stock.get("channel_counts", {})
        total_count = stock.get("total_count", overlap)

        if channel_counts:
            detail_parts = []
            for ch in ["뉴스", "경제방송", "유튜브", "애널리스트"]:
                cnt = channel_counts.get(ch, 0)
                if cnt > 0:
                    detail_parts.append(ch + " " + str(cnt) + "회")
            detail_str = " / ".join(detail_parts)
            overlap_badge = (
                '<span class="overlap-badge">총 ' + str(total_count)
                + '회 언급 (' + detail_str + ')</span>'
            )
        else:
            overlap_badge = (
                '<span class="overlap-badge">'
                + str(overlap) + '개 채널 언급</span>'
            )

        source_tags = ""
        for st in source_types:
            source_tags += '<span class="source-tag">' + st + '</span>'

        price_info_text = ""
        if verified_price:
            p = verified_price
            change_val = p.get("change", "")
            if change_val.startswith("+"):
                sign = "▲"
            elif change_val.startswith("-"):
                sign = "▼"
            else:
                sign = ""
            change_display = change_val.lstrip("+-") if change_val else ""
            change_pct_display = p.get("change_pct", "")
            if sign and change_display:
                price_info_text = (
                    " (" + p["price"] + "원 "
                    + sign + change_display + " "
                    + change_pct_display + ")"
                )
            else:
                price_info_text = " (" + p["price"] + "원)"
        elif market == "해외":
            price_info_text = " (해외 종목)"

        # ✅ 차트보기: naver_code 있으면 종목 페이지, 없으면 stock_map 폴백
        chart_btn_html = ""
        if chart_b64:
            chart_btn_html = (
                ' <span class="chart-icon"'
                ' onclick="openChartWindow(\'' + name + '\', \'' + str(rank) + '\')"'
                ' title="14일 주가 차트 보기">&#x1F4C8; 차트보기</span>'
            )
        else:
            if naver_code:
                naver_url = "https://finance.naver.com/item/main.naver?code=" + naver_code
            else:
                naver_url = (
                    "https://finance.naver.com/search/searchResult.naver?query="
                    + requests.utils.quote(name)
                )
            chart_btn_html = (
                ' <a href="' + naver_url + '" target="_blank"'
                ' class="chart-icon" title="네이버 금융에서 차트 보기">'
                '&#x1F4C8; 차트보기</a>'
            )

        reasons_html = ""
        for reason in reasons:
            rs = reason.get("source_type", "")
            rn = reason.get("source_name", "")
            rd = reason.get("detail", "")
            rurl = reason.get("source_url", "")
            if not rurl and "애널리스트" in rs:
                rurl = (
                    "https://finance.naver.com/research/company_list.naver"
                    "?searchType=itemCode&itemName="
                    + requests.utils.quote(name)
                )
            link_html = ""
            if rurl:
                link_html = (
                    ' <a href="' + rurl + '" target="_blank"'
                    ' class="source-link" title="원본 보기">&#x1F517; 바로보기</a>'
                )
            reasons_html += (
                '<div class="reason-item">'
                '<div class="reason-header">'
                '<span class="reason-source">[' + rs + '] ' + rn + '</span>'
                + link_html
                + '</div>'
                '<p class="reason-detail">' + rd + '</p>'
                '</div>'
            )

        stocks_html += (
            '<div class="stock-card">'
            '<div class="stock-header">'
            '<span class="stock-rank">#' + str(rank) + '</span>'
            '<span class="stock-name">' + name + '</span>'
            '<span class="stock-signal ' + signal_class + '">' + signal + '</span>'
            + overlap_badge
            + '</div>'
            '<div class="source-tags">' + source_tags + '</div>'
            '<div class="info-block"><h4>&#x1F4CB; 종목 요약</h4>'
            '<p>' + description + '</p></div>'
            '<div class="info-block">'
            '<h4>&#x1F4C8; 주가 흐름' + price_info_text + chart_btn_html + '</h4>'
            '<p>' + price_trend + '</p></div>'
            '<div class="info-block"><h4>&#x1F680; 상승 촉매</h4>'
            '<p>' + catalyst + '</p></div>'
            '<div class="info-block"><h4>&#x26A0;&#xFE0F; 리스크</h4>'
            '<p>' + risk + '</p></div>'
            '<div class="reasons-section">'
            '<h4>&#x1F4E2; 채널별 언급 내용</h4>'
            + reasons_html
            + '</div>'
            '</div>\n'
        )

    # ── hidden picks ──
    hidden_html = ""
    for hp in hidden_picks:
        hp_name = hp.get("name", "")
        hp_rank = hp.get("rank", "")
        hp_desc = hp.get("description", "")
        hp_catalyst = hp.get("catalyst", "")
        hp_risk = hp.get("risk", "")
        hp_reasons = hp.get("reasons", [])
        hp_verified = hp.get("verified_price")
        hp_market = hp.get("market", "국내")
        hp_chart_b64 = hp.get("chart_base64")
        hp_naver_code = hp.get("naver_code", "")
        if not hp_naver_code and hp_verified:
            hp_naver_code = hp_verified.get("code", "")

        hp_price_html = ""
        if hp_verified:
            p = hp_verified
            change_val = p.get("change", "")
            if change_val.startswith("+"):
                change_class = "price-up"
            elif change_val.startswith("-"):
                change_class = "price-down"
            else:
                change_class = "price-note"
            hp_price_html = (
                '<div class="price-box">'
                '<span class="current-price">' + p["price"] + '&#xC6D0;</span>'
                '<span class="' + change_class + '">'
                + (change_val + ' (' + p.get("change_pct", "") + ')' if change_val else "등락 정보 없음")
                + '</span>'
                '</div>'
            )
        elif hp_market == "해외":
            hp_price_html = (
                '<div class="price-box">'
                '<span class="price-note">해외 종목 (실시간 가격 미제공)</span>'
                '</div>'
            )

        hp_chart_btn = ""
        if hp_chart_b64:
            hp_chart_btn = (
                ' <span class="chart-icon"'
                ' onclick="openChartWindow(\'' + hp_name + '\', \'hp_' + str(hp_rank) + '\')"'
                ' title="14일 주가 차트 보기">&#x1F4C8; 차트보기</span>'
            )
        else:
            if hp_naver_code:
                hp_naver_url = "https://finance.naver.com/item/main.naver?code=" + hp_naver_code
            else:
                hp_naver_url = (
                    "https://finance.naver.com/search/searchResult.naver?query="
                    + requests.utils.quote(hp_name)
                )
            hp_chart_btn = (
                ' <a href="' + hp_naver_url + '" target="_blank"'
                ' class="chart-icon" title="네이버 금융에서 차트 보기">'
                '&#x1F4C8; 차트보기</a>'
            )

        hp_reasons_html = ""
        for reason in hp_reasons:
            rs = reason.get("source_type", "")
            rn = reason.get("source_name", "")
            rd = reason.get("detail", "")
            rurl = reason.get("source_url", "")
            if not rurl and "애널리스트" in rs:
                rurl = (
                    "https://finance.naver.com/research/company_list.naver"
                    "?searchType=itemCode&itemName="
                    + requests.utils.quote(hp_name)
                )
            link_html = ""
            if rurl:
                link_html = (
                    ' <a href="' + rurl + '" target="_blank"'
                    ' class="source-link" title="원본 보기">&#x1F517; 바로보기</a>'
                )
            hp_reasons_html += (
                '<div class="reason-item">'
                '<div class="reason-header">'
                '<span class="reason-source">[' + rs + '] ' + rn + '</span>'
                + link_html
                + '</div>'
                '<p class="reason-detail">' + rd + '</p>'
                '</div>'
            )

        hidden_html += (
            '<div class="hidden-pick-card">'
            '<div class="stock-header">'
            '<span class="stock-rank">Hidden #' + str(hp_rank) + '</span>'
            '<span class="stock-name">' + hp_name + '</span>'
            '</div>'
            + hp_price_html
            + '<div class="info-block"><h4>&#x1F4CB; 기업 소개</h4>'
            '<p>' + hp_desc + '</p></div>'
            '<div class="info-block">'
            '<h4>&#x1F680; 주목 이유' + hp_chart_btn + '</h4>'
            '<p>' + hp_catalyst + '</p></div>'
            '<div class="info-block"><h4>&#x26A0;&#xFE0F; 리스크</h4>'
            '<p>' + hp_risk + '</p></div>'
            '<div class="reasons-section">'
            '<h4>&#x1F4E2; 채널별 언급 내용</h4>'
            + hp_reasons_html
            + '</div>'
            '</div>\n'
        )

    # ── JavaScript 차트 데이터 맵 ──
    chart_data_js = "var chartDataMap = {};\n"
    for stock in stocks:
        b64 = stock.get("chart_base64")
        if b64:
            chart_data_js += (
                'chartDataMap["' + str(stock.get("rank", ""))
                + '"] = "data:image/png;base64,' + b64 + '";\n'
            )
    for hp in hidden_picks:
        b64 = hp.get("chart_base64")
        if b64:
            chart_data_js += (
                'chartDataMap["hp_' + str(hp.get("rank", ""))
                + '"] = "data:image/png;base64,' + b64 + '";\n'
            )

    # ── 아카이브 링크 (GitHub API 방식) ──
    archive_links = ""
    if gh_repo:
        try:
            repo_owner = gh_repo.split("/")[0]
            repo_name = gh_repo.split("/")[1]
            api_url = (
                "https://api.github.com/repos/"
                + repo_owner + "/" + repo_name
                + "/contents/docs/archive"
            )
            resp = requests.get(api_url, timeout=10)
            if resp.status_code == 200:
                files = resp.json()
                html_files = sorted(
                    [f["name"] for f in files if f["name"].endswith(".html")],
                    reverse=True,
                )
                for af in html_files[:14]:
                    date_str = af.replace(".html", "")
                    archive_links += (
                        '<a href="https://' + repo_owner + '.github.io/'
                        + repo_name + '/archive/' + af
                        + '" class="archive-link">' + date_str + '</a>\n'
                    )
        except Exception:
            pass

    # ── HTML 조립 ──
    html = (
        '<!DOCTYPE html>\n'
        '<html lang="ko">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '<title>AI 주식 브리핑 - ' + briefing_date + '</title>\n'
        '<style>\n'
        '* { margin: 0; padding: 0; box-sizing: border-box; }\n'
        'body { font-family: \'Pretendard\', -apple-system, BlinkMacSystemFont, '
        '\'Segoe UI\', Roboto, sans-serif; background: #0a0a14; color: #e0e0e0; line-height: 1.6; }\n'
        '.container { max-width: 800px; margin: 0 auto; padding: 20px; }\n'
        '.header { text-align: center; padding: 30px 0; border-bottom: 1px solid #1e1e2e; margin-bottom: 30px; }\n'
        '.header h1 { font-size: 1.8em; color: #fff; margin-bottom: 8px; }\n'
        '.header .date { color: #888; font-size: 0.95em; }\n'
        '.header .desc { color: #aaa; font-size: 0.85em; margin-top: 8px; }\n'
        '.section { margin-bottom: 35px; }\n'
        '.section-title { font-size: 1.3em; color: #fff; margin-bottom: 15px; '
        'padding-left: 12px; border-left: 3px solid #667eea; }\n'
        '.summary-block { background: #141420; border-radius: 12px; padding: 18px; '
        'margin-bottom: 12px; border: 1px solid #1e1e2e; }\n'
        '.summary-subtitle { color: #667eea; font-size: 1.05em; margin-bottom: 8px; }\n'
        '.summary-text { color: #ccc; font-size: 0.92em; }\n'
        '.sector-badge { display: inline-block; background: linear-gradient(135deg, #667eea20, #764ba220); '
        'color: #a8b4ff; padding: 6px 14px; border-radius: 20px; margin: 4px; '
        'font-size: 0.85em; border: 1px solid #667eea40; }\n'
        '.stock-card, .hidden-pick-card { background: #141420; border-radius: 12px; '
        'padding: 20px; margin-bottom: 16px; border: 1px solid #1e1e2e; transition: border-color 0.3s; }\n'
        '.stock-card:hover, .hidden-pick-card:hover { border-color: #667eea60; }\n'
        '.stock-header { display: flex; align-items: center; gap: 10px; '
        'margin-bottom: 12px; flex-wrap: wrap; }\n'
        '.stock-rank { background: #667eea; color: #fff; padding: 2px 10px; '
        'border-radius: 12px; font-size: 0.85em; font-weight: 700; }\n'
        '.stock-name { font-size: 1.15em; font-weight: 700; color: #fff; }\n'
        '.stock-signal { padding: 3px 10px; border-radius: 10px; font-size: 0.8em; font-weight: 600; }\n'
        '.signal-positive { background: #ff6b6b20; color: #ff6b6b; border: 1px solid #ff6b6b40; }\n'
        '.signal-negative { background: #339af020; color: #339af0; border: 1px solid #339af040; }\n'
        '.signal-neutral { background: #ffd43b20; color: #ffd43b; border: 1px solid #ffd43b40; }\n'
        '.overlap-badge { background: #51cf6620; color: #51cf66; padding: 3px 10px; '
        'border-radius: 10px; font-size: 0.8em; border: 1px solid #51cf6640; }\n'
        '.source-tags { margin-bottom: 12px; }\n'
        '.source-tag { display: inline-block; background: #1e1e2e; color: #888; '
        'padding: 3px 8px; border-radius: 6px; font-size: 0.75em; margin: 2px; }\n'
        '.price-box { margin-bottom: 12px; padding: 10px; background: #1a1a2e; border-radius: 8px; }\n'
        '.current-price { font-size: 1.3em; font-weight: 700; color: #fff; margin-right: 10px; }\n'
        '.price-up { color: #ff6b6b; font-weight: 600; }\n'
        '.price-down { color: #339af0; font-weight: 600; }\n'
        '.price-note { color: #888; font-size: 0.85em; }\n'
        '.chart-icon { cursor: pointer; color: #667eea; font-size: 0.85em; '
        'padding: 3px 8px; border-radius: 6px; background: #667eea15; '
        'border: 1px solid #667eea30; margin-left: 4px; white-space: nowrap; '
        'text-decoration: none; display: inline-block; }\n'
        '.chart-icon:hover { background: #667eea30; }\n'
        '.info-block { margin-bottom: 12px; }\n'
        '.info-block h4 { color: #a8b4ff; font-size: 0.9em; margin-bottom: 4px; '
        'display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }\n'
        '.info-block p { color: #bbb; font-size: 0.88em; }\n'
        '.reasons-section { margin-top: 12px; }\n'
        '.reasons-section h4 { color: #a8b4ff; font-size: 0.9em; margin-bottom: 8px; }\n'
        '.reason-item { background: #1a1a2e; border-radius: 8px; padding: 10px; margin-bottom: 6px; }\n'
        '.reason-header { display: flex; align-items: center; gap: 8px; '
        'margin-bottom: 4px; flex-wrap: wrap; }\n'
        '.reason-source { color: #667eea; font-size: 0.82em; font-weight: 600; }\n'
        '.source-link { color: #51cf66; font-size: 0.78em; text-decoration: none; }\n'
        '.source-link:hover { text-decoration: underline; }\n'
        '.reason-detail { color: #aaa; font-size: 0.85em; }\n'
        '.strategy-block { background: linear-gradient(135deg, #141420, #1a1a2e); '
        'border: 1px solid #667eea30; border-radius: 12px; padding: 20px; }\n'
        '.strategy-block p { color: #ccc; font-size: 0.92em; line-height: 1.8; }\n'
        '.disclaimer { text-align: center; color: #666; font-size: 0.78em; '
        'margin-top: 30px; padding: 15px; border-top: 1px solid #1e1e2e; }\n'
        '.archive-section { margin-top: 20px; }\n'
        '.archive-link { display: inline-block; color: #667eea; text-decoration: none; '
        'padding: 4px 10px; margin: 3px; border: 1px solid #667eea30; '
        'border-radius: 6px; font-size: 0.82em; }\n'
        '.archive-link:hover { background: #667eea20; }\n'
        '.hidden-pick-card { border-left: 3px solid #ffd43b; }\n'
        '.chart-modal { display: none; position: fixed; top: 0; left: 0; '
        'width: 100%; height: 100%; background: rgba(0,0,0,0.85); '
        'z-index: 1000; justify-content: center; align-items: center; }\n'
        '.chart-modal img { max-width: 95%; max-height: 80%; border-radius: 8px; }\n'
        '.chart-modal .close-btn { position: absolute; top: 20px; right: 30px; '
        'color: #fff; font-size: 2em; cursor: pointer; }\n'
        '</style>\n'
        '</head>\n'
        '<body>\n'
        '<div class="container">\n'
        '    <div class="header">\n'
        '        <h1>&#x1F4CA; AI 주식 브리핑</h1>\n'
        '        <div class="date">' + briefing_datetime + ' 기준</div>\n'
        '        <div class="desc">최근 뉴스와 경제방송, 구독자 상위권 유튜브, '
        '증권사 보고서에서 공통으로 언급된 종목들에 대한 브리핑입니다.</div>\n'
        '    </div>\n'
        '\n'
        '    <div class="section">\n'
        '        <h2 class="section-title">&#x1F30D; 시장 요약</h2>\n'
        '        ' + formatted_summary + '\n'
        '    </div>\n'
        '\n'
        '    <div class="section">\n'
        '        <h2 class="section-title">&#x1F525; 주목 섹터</h2>\n'
        '        ' + sectors_html + '\n'
        '    </div>\n'
        '\n'
        '    <div class="section">\n'
        '        <h2 class="section-title">&#x1F3AF; 관심 종목</h2>\n'
        '        ' + stocks_html + '\n'
        '    </div>\n'
    )

    if hidden_html:
        html += (
            '\n'
            '    <div class="section">\n'
            '        <h2 class="section-title">&#x1F48E; 히든픽</h2>\n'
            '        ' + hidden_html + '\n'
            '    </div>\n'
        )

    # ✅ 'AI 최종 요약' → 'AI 투자 전략'으로 변경
    if investment_strategy:
        html += (
            '\n'
            '    <div class="section">\n'
            '        <h2 class="section-title">&#x1F4B0; AI 투자 전략</h2>\n'
            '        <div class="strategy-block">\n'
            '            <p>' + investment_strategy + '</p>\n'
            '        </div>\n'
            '    </div>\n'
        )

    if archive_links:
        html += (
            '\n'
            '    <div class="section archive-section">\n'
            '        <h2 class="section-title">&#x1F4C5; 지난 브리핑</h2>\n'
            '        ' + archive_links + '\n'
            '    </div>\n'
        )

    html += (
        '\n'
        '    <div class="disclaimer">\n'
        '        &#x26A0;&#xFE0F; 본 브리핑은 AI가 자동 생성한 참고 자료이며, 투자 권유가 아닙니다.<br>\n'
        '        투자 판단의 책임은 투자자 본인에게 있습니다.\n'
        '    </div>\n'
        '</div>\n'
        '\n'
        '<div class="chart-modal" id="chartModal" onclick="closeChart()">\n'
        '    <span class="close-btn" onclick="closeChart()">&times;</span>\n'
        '    <img id="chartImg" src="" alt="차트">\n'
        '</div>\n'
        '\n'
        '<script>\n'
        + chart_data_js
        + '\n'
        'function openChartWindow(stockName, chartKey) {\n'
        '    var src = chartDataMap[chartKey];\n'
        '    if (src) {\n'
        '        document.getElementById(\'chartImg\').src = src;\n'
        '        document.getElementById(\'chartModal\').style.display = \'flex\';\n'
        '    }\n'
        '}\n'
        'function closeChart() {\n'
        '    document.getElementById(\'chartModal\').style.display = \'none\';\n'
        '}\n'
        'document.addEventListener(\'keydown\', function(e) {\n'
        '    if (e.key === \'Escape\') closeChart();\n'
        '});\n'
        '</script>\n'
        '</body>\n'
        '</html>'
    )

    return html
