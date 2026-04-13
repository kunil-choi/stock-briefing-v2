import anthropic
import time

CLAUDE_MODELS = [
    "claude-sonnet-4-6",          # ✅ 현재 최신 모델
    "claude-3-5-sonnet-20241022", # ✅ 검증된 폴백
    "claude-3-5-haiku-20241022",  # ✅ 경량 폴백
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
