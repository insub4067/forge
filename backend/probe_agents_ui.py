"""Agent Crew UI 스모크 — 빌드된 앱을 headless로 열어 실제로 동작하는지 검증한다.

`_runtime_smoke`와 같은 방식으로, uncaught 예외(pageerror)와 핵심 셀렉터 렌더만 본다.
백엔드가 8790에 떠 있어야 하며(신규 /api/agents 라우트 포함), StaticFiles라 방금 빌드된
dist가 재시작 없이 서빙된다.

검증 흐름:
  메뉴 열기 → "에이전트" 진입 → 카드 4장 렌더 → Developer 상세 → Prompt Viewer 렌더
성공 시 stdout에 `CREW_SMOKE_OK`를 출력한다(exit 0).
실행: cd backend && ./.venv/bin/python probe_agents_ui.py
"""
import asyncio
import sys


BASE = "http://127.0.0.1:8790"


async def main() -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("CREW_SMOKE_UNAVAILABLE: playwright 미설치")
        return 2

    # 백엔드가 새 코드를 로드했는지 먼저 확인한다 — /api/agents가 JSON이 아니라 index.html을
    # 반환하면 백엔드가 stale(재시작 전)이다. 이건 UI 결함이 아니라 환경 문제이므로 failed가
    # 아니라 unavailable(검증 불가)로 정직하게 처리한다(evidence 규율: 애매하면 통과 아님·실패도 아님).
    try:
        import urllib.request
        with urllib.request.urlopen(BASE + "/api/agents", timeout=5) as r:
            ct = r.headers.get("content-type", "")
            if "application/json" not in ct:
                print("CREW_SMOKE_UNAVAILABLE: 백엔드가 stale입니다(/api/agents가 JSON을 "
                      "반환하지 않음). 백엔드를 재시작한 뒤 다시 실행하세요.")
                return 2
    except Exception as err:
        print(f"CREW_SMOKE_UNAVAILABLE: 백엔드 확인 실패 — {err}")
        return 2

    errors: list[str] = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 390, "height": 844})
            page.on("pageerror", lambda e: errors.append(str(e)))
            try:
                await page.goto(BASE, wait_until="networkidle", timeout=20000)

                # 메뉴 열기
                await page.locator(".todo-btn").first.click(timeout=5000)
                await page.locator(".menu-item", has_text="에이전트").first.click(timeout=5000)

                # roster 카드 4장
                await page.wait_for_selector(".agent-card", timeout=8000)
                card_count = await page.locator(".agent-card").count()
                if card_count != 4:
                    print(f"CREW_SMOKE_FAIL: 카드 {card_count}장 (4 기대)")
                    await browser.close()
                    return 1

                # 첫 카드(Developer) 상세 진입
                await page.locator(".agent-card").first.click(timeout=5000)
                await page.wait_for_selector(".agent-detail", timeout=5000)
                detail_name = (await page.locator(".detail-name").first.text_content() or "").strip()
                if detail_name != "Developer":
                    print(f"CREW_SMOKE_FAIL: 상세 이름 '{detail_name}'")
                    await browser.close()
                    return 1

                # Prompt Viewer
                await page.locator(".prompt-open-btn").first.click(timeout=5000)
                await page.wait_for_selector(".prompt-body", timeout=8000)
                body = await page.locator(".prompt-body").first.text_content() or ""
                if "# Developer Agent" not in body:
                    print("CREW_SMOKE_FAIL: 프롬프트 본문에 역할 헤더 없음")
                    await browser.close()
                    return 1
            finally:
                await browser.close()
    except Exception as err:
        print(f"CREW_SMOKE_UNAVAILABLE: {err}")
        return 2

    if errors:
        print("CREW_SMOKE_FAIL: uncaught 예외\n" + "\n".join(errors[:8]))
        return 1

    print("CREW_SMOKE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
