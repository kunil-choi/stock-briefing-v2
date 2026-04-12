# collectors/youtube_collector.py
import os
import re
import requests
from datetime import datetime, timezone, timedelta

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

from config import (
    YOUTUBE_API_KEY,
    POPULAR_PANELISTS,
    YOUTUBER_HOURS,
    BROADCAST_HOURS,
)

API_KEY = YOUTUBE_API_KEY

# 주식/경제 관련 키워드 (제목 필터링)
STOCK_KEYWORDS = [
    "주식", "종목", "매수", "매도", "코스피", "코스닥", "상장", "실적",
    "반도체", "배터리", "2차전지", "바이오", "AI", "로봇", "방산", "원전",
    "ETF", "배당", "테마주", "급등", "목표가", "투자", "증시", "시황",
    "포트폴리오", "리밸런싱", "금리", "환율", "채권", "국채", "달러",
    "인플레이션", "경기", "FOMC", "연준", "GDP", "CPI", "고용",
    "부동산", "전세", "매매", "분양", "재건축", "재개발",
    "엔비디아", "테슬라", "삼성전자", "SK하이닉스", "애플", "마이크로소프트",
    "S&P", "나스닥", "다우", "미국장", "뉴욕증시", "해외주식",
    "상승", "하락", "전망", "분석", "추천", "리포트", "브리핑",
    "성공예감", "경제", "금융", "거시", "글로벌", "시장",
]


def test_api_key():
    """YouTube API 키 유효성 테스트"""
    if not API_KEY:
        print("[YouTube] API 키가 설정되지 않았습니다.")
        return False
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"part": "snippet", "id": "dQw4w9WgXcQ", "key": API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            print("[YouTube] API 키 테스트 성공 ✅")
            return True
        else:
            err = resp.json().get("error", {})
            print(f"[YouTube] API 키 테스트 실패 ❌ 코드:{resp.status_code} 메시지:{err.get('message','')}")
            return False
    except Exception as e:
        print(f"[YouTube] API 키 테스트 오류: {e}")
        return False


def get_uploads_playlist_id(channel_id):
    """채널 ID에서 업로드 재생목록 ID를 추출 (UC... → UU...)"""
    if channel_id.startswith("UC"):
        return "UU" + channel_id[2:]
    return None


def get_recent_videos_via_playlist(channel_id, api_key, hours=24, max_results=15):
    """
    playlistItems.list를 사용하여 최근 영상 가져오기 (1유닛/호출)
    search.list (100유닛/호출) 대비 1/100 비용
    """
    playlist_id = get_uploads_playlist_id(channel_id)
    if not playlist_id:
        print(f"    업로드 재생목록 ID 변환 실패: {channel_id}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    url = "https://www.googleapis.com/youtube/v3/playlistItems"
    params = {
        "part": "snippet",
        "playlistId": playlist_id,
        "maxResults": max_results,
        "key": api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()

        if "error" in data:
            err = data["error"]
            print(f"    API 오류: {err.get('code')} - {err.get('message','')}")
            if err.get("errors"):
                for e in err["errors"]:
                    print(f"      reason: {e.get('reason')}, domain: {e.get('domain')}")
            return []

        items = data.get("items", [])

        # 시간 필터링: cutoff 이후 영상만
        recent_items = []
        for item in items:
            snippet = item.get("snippet", {})
            published_str = snippet.get("publishedAt", "")
            if not published_str:
                continue
            try:
                published_dt = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                if published_dt >= cutoff:
                    # search.list와 동일한 형식으로 변환
                    video_id = snippet.get("resourceId", {}).get("videoId", "")
                    recent_items.append({
                        "id": {"videoId": video_id},
                        "snippet": {
                            "title": snippet.get("title", ""),
                            "description": snippet.get("description", ""),
                            "publishedAt": published_str,
                            "channelId": snippet.get("channelId", ""),
                            "channelTitle": snippet.get("channelTitle", ""),
                        }
                    })
                else:
                    # 최신순 정렬이므로, cutoff 이전이면 중단
                    break
            except Exception:
                continue

        print(f"    최근 {hours}시간 영상: {len(recent_items)}개 (전체 {len(items)}개 중)")
        return recent_items

    except Exception as e:
        print(f"    요청 오류: {e}")
        return []


def resolve_channel_id(channel_id_or_handle, api_key):
    """@handle 형식을 실제 채널 ID로 변환 (1유닛)"""
    if channel_id_or_handle.startswith("UC") and len(channel_id_or_handle) == 24:
        return channel_id_or_handle

    if channel_id_or_handle.startswith("@") or (not channel_id_or_handle.startswith("UC")):
        handle = channel_id_or_handle.lstrip("@")
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {"part": "id", "forHandle": handle, "key": api_key}
        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if data.get("items"):
                resolved = data["items"][0]["id"]
                print(f"  [ID변환] @{handle} → {resolved}")
                return resolved
        except Exception as e:
            print(f"  [ID변환 실패] @{handle}: {e}")

    return channel_id_or_handle


def get_transcript(video_id, max_chars=2000):
    """유튜브 영상 자막 추출"""
    if YouTubeTranscriptApi is None:
        return ""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            transcript = transcript_list.find_transcript(["ko"])
        except Exception:
            try:
                transcript = transcript_list.find_generated_transcript(["ko"])
            except Exception:
                return ""
        entries = transcript.fetch()
        text = " ".join([e.get("text", e.get("value", "")) if isinstance(e, dict) else str(e) for e in entries])
        return text[:max_chars]
    except Exception:
        return ""


def is_stock_related(title, description=""):
    """제목이나 설명에 주식/경제 키워드가 포함되어 있는지 확인"""
    text = (title + " " + description).lower()
    for keyword in STOCK_KEYWORDS:
        if keyword.lower() in text:
            return True
    return False


def has_popular_panelist(title, description=""):
    """인기 패널이 제목이나 설명에 언급되어 있는지 확인"""
    text = title + " " + description
    matched = []
    for panelist in POPULAR_PANELISTS:
        if panelist in text:
            matched.append(panelist)
    return matched


def load_channels_safe():
    """channels.json을 안전하게 로드"""
    try:
        from config import load_channels
        return load_channels()
    except Exception as e:
        print(f"  [channels.json 로드 실패] {e}")
        return {}


def collect_broadcast_youtube():
    """경제전문방송 유튜브 수집 (playlistItems 사용, 1유닛/채널)"""
    print("\n=== 경제전문방송 유튜브 수집 ===")

    if not test_api_key():
        return []

    results = []
    channels_data = load_channels_safe()
    broadcast_channels = {}

    for name, info in channels_data.get("broadcast", {}).items():
        ch_id = info.get("id", "") if isinstance(info, dict) else info
        broadcast_channels[name] = ch_id

    if not broadcast_channels:
        print("  방송 채널 목록이 비어있습니다.")
        return []

    for name, channel_id in broadcast_channels.items():
        print(f"\n[방송] {name} ({channel_id})")

        # 채널 ID가 UC로 시작하지 않으면 변환 시도
        if not channel_id.startswith("UC"):
            channel_id = resolve_channel_id(channel_id, API_KEY)

        videos = get_recent_videos_via_playlist(channel_id, API_KEY, hours=BROADCAST_HOURS, max_results=15)

        collected = 0
        for item in videos:
            snippet = item.get("snippet", {})
            title = snippet.get("title", "")
            desc = snippet.get("description", "")
            video_id = item.get("id", {}).get("videoId", "")

            if not is_stock_related(title, desc):
                continue

            transcript = get_transcript(video_id, max_chars=1500)
            summary = transcript if transcript else desc[:500]

            results.append({
                "source_type": "경제방송",
                "source_name": name,
                "title": title,
                "summary": summary,
                "link": f"https://www.youtube.com/watch?v={video_id}",
                "published": snippet.get("publishedAt", ""),
            })
            collected += 1

        print(f"  → 경제관련 {collected}개 수집")

    print(f"\n[경제방송 합계] {len(results)}개")
    return results


def collect_youtuber():
    """오리지널 유튜브 채널 수집 (TOP50 + youtuber, playlistItems 사용)"""
    print("\n=== 오리지널 유튜브 채널 수집 (TOP50 + 인기패널) ===")

    if not test_api_key():
        return []

    results = []
    channels_data = load_channels_safe()

    # 1) channels.json의 top50 + youtuber 병합 (중복 제거)
    all_channels = {}

    for name, info in channels_data.get("top50", {}).items():
        ch_id = info.get("id", "") if isinstance(info, dict) else info
        all_channels[name] = ch_id

    for name, info in channels_data.get("youtuber", {}).items():
        ch_id = info.get("id", "") if isinstance(info, dict) else info
        if name not in all_channels:
            all_channels[name] = ch_id

    if not all_channels:
        print("  유튜버 채널 목록이 비어있습니다.")
        return []

    print(f"총 수집 대상 채널: {len(all_channels)}개")

    # 2) 각 채널에서 최근 영상 수집 (playlistItems = 1유닛/채널)
    for name, channel_id in all_channels.items():
        print(f"\n[유튜버] {name}")

        if not channel_id.startswith("UC"):
            channel_id = resolve_channel_id(channel_id, API_KEY)

        videos = get_recent_videos_via_playlist(channel_id, API_KEY, hours=YOUTUBER_HOURS, max_results=10)

        collected = 0
        for item in videos:
            snippet = item.get("snippet", {})
            title = snippet.get("title", "")
            desc = snippet.get("description", "")
            video_id = item.get("id", {}).get("videoId", "")

            if not is_stock_related(title, desc):
                continue

            panelists = has_popular_panelist(title, desc)
            transcript = get_transcript(video_id, max_chars=1500)
            summary = transcript if transcript else desc[:500]

            source_label = name
            if panelists:
                source_label = f"{name} (패널: {', '.join(panelists)})"

            results.append({
                "source_type": "유튜버",
                "source_name": source_label,
                "title": title,
                "summary": summary,
                "link": f"https://www.youtube.com/watch?v={video_id}",
                "published": snippet.get("publishedAt", ""),
                "panelists": panelists,
            })
            collected += 1

        print(f"  → {collected}개 수집")

    print(f"\n[유튜버 합계] {len(results)}개")
    return results
