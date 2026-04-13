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
    final_summary = data.get("final_summary", "")

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

        # 주가 정보를 주가흐름 제목에 통합
        price_info_text = ""
        if verified_price:
            p = verified_price
            sign = "▲" if p.get("change", "").startswith("+") else "▼"
            price_info_text = " (" + p["price"] + "원 " + sign + p.get("change", "").lstrip("+-") + " " + p.get("change_pct", "") + ")"
        elif market == "해외":
            price_info_text = " (해외 종목)"

        chart_btn_html = ""
        if chart_b64:
            chart_btn_html = ' <span class="chart-icon" onclick="openChartWindow(\'' + name + '\', \'x\')" data-chart="' + str(rank) + '" title="14일 주가 차트 보기">&#x1F4C8; 차트보기</span>'
        else:
            naver_url = "https://finance.naver.com/item/main.naver?query=" + requests.utils.quote(name)
            chart_btn_html = ' <a href="' + naver_url + '" target="_blank" class="chart-icon" title="네이버 금융에서 차트 보기">&#x1F4C8; 차트보기</a>'
    
        reasons_html = ""
        for reason in reasons:
            rs = reason.get("source_type", "")
            rn = reason.get("source_name", "")
            rd = reason.get("detail", "")
            rurl = reason.get("source_url", "")
            if not rurl and "애널리스트" in rs:
                rurl = "https://finance.naver.com/research/company_list.naver?searchType=itemCode&itemName=" + requests.utils.quote(name)
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
            + '<div class="source-tags">' + source_tags + '</div>'
            + '<div class="info-block"><h4>&#x1F4CB; 종목 요약</h4><p>' + description + '</p></div>'
            + '<div class="info-block"><h4>&#x1F4C8; 주가 흐름' + price_info_text + chart_btn_html + '</h4><p>' + price_trend + '</p></div>'
            + '<div class="info-block"><h4>&#x1F680; 상승 촉매</h4><p>' + catalyst + '</p></div>'
            + '<div class="info-block"><h4>&#x26A0;&#xFE0F; 리스크</h4><p>' + risk + '</p></div>'
            + '<div class="reasons-section"><h4>&#x1F4E2; 채널별 언급 내용</h4>' + reasons_html + '</div>'
            + '</div>\n')

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

        hp_price_html = ""
        if hp_verified:
            p = hp_verified
            change_class = "price-up" if p.get("change", "").startswith("+") else "price-down"
            hp_price_html = ('<div class="price-box">'
                + '<span class="current-price">' + p["price"] + '&#xC6D0;</span>'
                + '<span class="' + change_class + '">' + p.get("change", "") + ' (' + p.get("change_pct", "") + ')</span>'
                + '</div>')
        elif hp_market == "해외":
            hp_price_html = '<div class="price-box"><span class="price-note">해외 종목 (실시간 가격 미제공)</span></div>'

        hp_reasons_html = ""
        for reason in hp_reasons:
            rs = reason.get("source_type", "")
            rn = reason.get("source_name", "")
            rd = reason.get("detail", "")
            rurl = reason.get("source_url", "")
            if not rurl and "애널리스트" in rs:
                rurl = "https://finance.naver.com/research/company_list.naver?searchType=itemCode&itemName=" + requests.utils.quote(hp_name)
            link_html = ""
            if rurl:
                link_html = ' <a href="' + rurl + '" target="_blank" class="source-link" title="원본 보기">&#x1F517; 바로보기</a>'
            hp_reasons_html += ('<div class="reason-item">'
                + '<div class="reason-header">'
                + '<span class="reason-source">[' + rs + '] ' + rn + '</span>' + link_html
                + '</div>'
                + '<p class="reason-detail">' + rd + '</p>'
                + '</div>')

        hidden_html += ('<div class="hidden-pick-card">'
            + '<div class="stock-header">'
            + '<span class="stock-rank">Hidden #' + str(hp_rank) + '</span>'
            + '<span class="stock-name">' + hp_name + '</span>'
            + '</div>'
            + hp_price_html
            + '<div class="info-block"><h4>&#x1F4CB; 기업 소개</h4><p>' + hp_desc + '</p></div>'
            + '<div class="info-block"><h4>&#x1F680; 주목 이유</h4><p>' + hp_catalyst + '</p></div>'
            + '<div class="info-block"><h4>&#x26A0;&#xFE0F; 리스크</h4><p>' + hp_risk + '</p></div>'
            + '<div class="reasons-section"><h4>&#x1F4E2; 채널별 언급 내용</h4>' + hp_reasons_html + '</div>'
            + '</div>\n')

    chart_data_js = "var chartDataMap = {};\n"
    for stock in stocks:
        b64 = stock.get("chart_base64")
        if b64:
            chart_data_js += 'chartDataMap["' + str(stock.get("rank", "")) + '"] = "data:image/png;base64,' + b64 + '";\n'

    archive_links = ""
    if gh_repo:
        try:
            archive_dir = os.path.join("docs", "archive")
            if os.path.isdir(archive_dir):
                archive_files = sorted(
                    [f for f in os.listdir(archive_dir) if f.endswith(".html")],
                    reverse=True
                )
                repo_owner = gh_repo.split("/")[0]
                repo_name = gh_repo.split("/")[1]
                for af in archive_files[:14]:
                    date_str = af.replace(".html", "")
                    archive_links += '<a href="https://' + repo_owner + '.github.io/' + repo_name + '/archive/' + af + '" class="archive-link">' + date_str + '</a>\n'
        except Exception:
            pass

    html = '''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 주식 브리핑 - ''' + briefing_date + '''</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a14; color: #e0e0e0; line-height: 1.6; }
.container { max-width: 800px; margin: 0 auto; padding: 20px; }
.header { text-align: center; padding: 30px 0; border-bottom: 1px solid #1e1e2e; margin-bottom: 30px; }
.header h1 { font-size: 1.8em; color: #fff; margin-bottom: 8px; }
.header .date { color: #888; font-size: 0.95em; }
.header .desc { color: #aaa; font-size: 0.85em; margin-top: 8px; }
.section { margin-bottom: 35px; }
.section-title { font-size: 1.3em; color: #fff; margin-bottom: 15px; padding-left: 12px; border-left: 3px solid #667eea; }
.summary-block { background: #141420; border-radius: 12px; padding: 18px; margin-bottom: 12px; border: 1px solid #1e1e2e; }
.summary-subtitle { color: #667eea; font-size: 1.05em; margin-bottom: 8px; }
.summary-text { color: #ccc; font-size: 0.92em; }
.sector-badge { display: inline-block; background: linear-gradient(135deg, #667eea20, #764ba220); color: #a8b4ff; padding: 6px 14px; border-radius: 20px; margin: 4px; font-size: 0.85em; border: 1px solid #667eea40; }
.stock-card, .hidden-pick-card { background: #141420; border-radius: 12px; padding: 20px; margin-bottom: 16px; border: 1px solid #1e1e2e; transition: border-color 0.3s; }
.stock-card:hover, .hidden-pick-card:hover { border-color: #667eea60; }
.stock-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.stock-rank { background: #667eea; color: #fff; padding: 2px 10px; border-radius: 12px; font-size: 0.85em; font-weight: 700; }
.stock-name { font-size: 1.15em; font-weight: 700; color: #fff; }
.stock-signal { padding: 3px 10px; border-radius: 10px; font-size: 0.8em; font-weight: 600; }
.signal-positive { background: #ff6b6b20; color: #ff6b6b; border: 1px solid #ff6b6b40; }
.signal-negative { background: #339af020; color: #339af0; border: 1px solid #339af040; }
.signal-neutral { background: #ffd43b20; color: #ffd43b; border: 1px solid #ffd43b40; }
.overlap-badge { background: #51cf6620; color: #51cf66; padding: 3px 10px; border-radius: 10px; font-size: 0.8em; border: 1px solid #51cf6640; }
.source-tags { margin-bottom: 12px; }
.source-tag { display: inline-block; background: #1e1e2e; color: #888; padding: 3px 8px; border-radius: 6px; font-size: 0.75em; margin: 2px; }
.price-box { margin-bottom: 12px; padding: 10px; background: #1a1a2e; border-radius: 8px; }
.current-price { font-size: 1.3em; font-weight: 700; color: #fff; margin-right: 10px; }
.price-up { color: #ff6b6b; font-weight: 600; }
.price-down { color: #339af0; font-weight: 600; }
.price-note { color: #888; font-size: 0.85em; }
.chart-icon { cursor: pointer; color: #667eea; font-size: 0.85em; padding: 3px 8px; border-radius: 6px; background: #667eea15; border: 1px solid #667eea30; margin-left: 4px; white-space: nowrap; }
.chart-icon:hover { background: #667eea30; }
.info-block { margin-bottom: 12px; }
.info-block h4 { color: #a8b4ff; font-size: 0.9em; margin-bottom: 4px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.info-block p { color: #bbb; font-size: 0.88em; }
.reasons-section { margin-top: 12px; }
.reasons-section h4 { color: #a8b4ff; font-size: 0.9em; margin-bottom: 8px; }
.reason-item { background: #1a1a2e; border-radius: 8px; padding: 10px; margin-bottom: 6px; }
.reason-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; flex-wrap: wrap; }
.reason-source { color: #667eea; font-size: 0.82em; font-weight: 600; }
.source-link { color: #51cf66; font-size: 0.78em; text-decoration: none; }
.source-link:hover { text-decoration: underline; }
.reason-detail { color: #aaa; font-size: 0.85em; }
.final-summary { background: linear-gradient(135deg, #141420, #1a1a2e); border: 1px solid #667eea30; border-radius: 12px; padding: 20px; }
.final-summary p { color: #ccc; font-size: 0.92em; }
.disclaimer { text-align: center; color: #666; font-size: 0.78em; margin-top: 30px; padding: 15px; border-top: 1px solid #1e1e2e; }
.archive-section { margin-top: 20px; }
.archive-link { display: inline-block; color: #667eea; text-decoration: none; padding: 4px 10px; margin: 3px; border: 1px solid #667eea30; border-radius: 6px; font-size: 0.82em; }
.archive-link:hover { background: #667eea20; }
.hidden-pick-card { border-left: 3px solid #ffd43b; }
.chart-modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 1000; justify-content: center; align-items: center; }
.chart-modal img { max-width: 95%; max-height: 80%; border-radius: 8px; }
.chart-modal .close-btn { position: absolute; top: 20px; right: 30px; color: #fff; font-size: 2em; cursor: pointer; }
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>&#x1F4CA; AI 주식 브리핑</h1>
        <div class="date">''' + briefing_datetime + ''' 기준</div>
        <div class="desc">최근 뉴스와 경제방송, 구독자 상위권 유튜브, 증권사 보고서에서 공통으로 언급된 종목들에 대한 브리핑입니다.</div>
    </div>

    <div class="section">
        <h2 class="section-title">&#x1F30D; 시장 요약</h2>
        ''' + formatted_summary + '''
    </div>

    <div class="section">
        <h2 class="section-title">&#x1F525; 주목 섹터</h2>
        ''' + sectors_html + '''
    </div>

    <div class="section">
        <h2 class="section-title">&#x1F3AF; 관심 종목</h2>
        ''' + stocks_html + '''
    </div>
'''

    if hidden_html:
        html += '''
    <div class="section">
        <h2 class="section-title">&#x1F48E; 히든픽</h2>
        ''' + hidden_html + '''
    </div>
'''

    html += '''
    <div class="section">
        <h2 class="section-title">&#x1F4DD; AI 최종 요약</h2>
        <div class="final-summary">
            <p>''' + final_summary + '''</p>
        </div>
    </div>
'''

    if archive_links:
        html += '''
    <div class="section archive-section">
        <h2 class="section-title">&#x1F4C5; 지난 브리핑</h2>
        ''' + archive_links + '''
    </div>
'''

    html += '''
    <div class="disclaimer">
        &#x26A0;&#xFE0F; 본 브리핑은 AI가 자동 생성한 참고 자료이며, 투자 권유가 아닙니다.<br>
        투자 판단의 책임은 투자자 본인에게 있습니다.
    </div>
</div>

<div class="chart-modal" id="chartModal" onclick="closeChart()">
    <span class="close-btn" onclick="closeChart()">&times;</span>
    <img id="chartImg" src="" alt="차트">
</div>

<script>
''' + chart_data_js + '''
function openChartWindow(stockName, x) {
    var el = event.target.closest('[data-chart]');
    if (!el) return;
    var key = el.getAttribute('data-chart');
    var src = chartDataMap[key];
    if (src) {
        document.getElementById('chartImg').src = src;
        document.getElementById('chartModal').style.display = 'flex';
    }
}
function closeChart() {
    document.getElementById('chartModal').style.display = 'none';
}
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeChart();
});
</script>
</body>
</html>'''

    return html
