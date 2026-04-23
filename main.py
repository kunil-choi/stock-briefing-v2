def main():
    print(f"=== AI 증시 모닝브리핑 시작: {datetime.now()} ===")

    # 채널 목록 로드
    print("\n[채널 로드]")
    channels = load_channels()

    all_data = []

    # 1. 뉴스
    print("\n[1/4] 뉴스 RSS 수집 중...")
    news_data = collect_news(NEWS_RSS_FEEDS)
    all_data.extend(news_data)
    print(f"  → 총 {len(news_data)}건")

    # 2. 경제방송
    print(f"\n[2/4] 경제전문방송 유튜브 수집 중 (최근 {BROADCAST_HOURS}시간)...")
    broadcast_data = collect_broadcast_youtube()
    all_data.extend(broadcast_data)
    print(f"  → 총 {len(broadcast_data)}건")

    # 3. 유튜버 (TOP50 + 인기패널)
    print(f"\n[3/4] 오리지널 경제유튜브 TOP50 + 인기패널 수집 중 (최근 {YOUTUBER_HOURS}시간)...")
    youtuber_data = collect_youtuber()
    all_data.extend(youtuber_data)
    print(f"  → 총 {len(youtuber_data)}건")

    # 4. 애널리스트
    print("\n[4/4] 애널리스트 리포트 수집 중...")
    analyst_data = collect_analyst()
    all_data.extend(analyst_data)
    print(f"  → 총 {len(analyst_data)}건")

    print(f"\n========== 전체 {len(all_data)}건 수집 완료 ==========")

    # 백업
    os.makedirs("data", exist_ok=True)
    today_str = datetime.now().strftime("%Y%m%d")
    with open(f"data/raw_{today_str}.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2, default=str)

    os.makedirs("docs", exist_ok=True)
    os.makedirs("docs/archive", exist_ok=True)

    # ✅ 순서 변경: 기존 index.html을 아카이브로 먼저 백업
    existing_index = "docs/index.html"
    if os.path.exists(existing_index):
        archive_date = datetime.now().strftime("%Y-%m-%d")
        archive_path = f"docs/archive/{archive_date}.html"
        if not os.path.exists(archive_path):
            shutil.copy2(existing_index, archive_path)
            print(f"✅ 아카이브 저장: {archive_path}")

    # ✅ 아카이브 백업 이후에 HTML 생성 → 오늘 날짜 파일이 archive에 존재하므로 링크에 포함됨
    print("\n[AI 분석] Claude API로 교차분석 중...")
    html = analyze_and_generate_html(all_data, ANTHROPIC_API_KEY, channels_data=channels, gh_repo=GITHUB_REPO)

    # 새 index.html 저장
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ 브리핑 페이지 생성 완료")
    print(f"=== 완료: {datetime.now()} ===")


if __name__ == "__main__":
    main()
