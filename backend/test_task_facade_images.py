"""task_facade 멀티모달 메시지 구성 검증 — LLM/네트워크 없이 build_user_content만 확인.

실행: python test_task_facade_images.py
"""
import os
import tempfile

from app.runtime import task_facade


def main():
    tmp = tempfile.mkdtemp()
    png = os.path.join(tmp, "shot.png")
    jpg = os.path.join(tmp, "chart.jpg")
    missing = os.path.join(tmp, "nope.png")
    with open(png, "wb") as f:
        f.write(b"\x89PNG fake")
    with open(jpg, "wb") as f:
        f.write(b"fake jpg")

    # 1) images 있음 → 리스트, text + image_url, url은 data:image
    content = task_facade.build_user_content("스크린샷 보고 고쳐", images=[png])
    assert isinstance(content, list), content
    assert content[0] == {"type": "text", "text": "스크린샷 보고 고쳐"}, content
    img = content[1]
    assert img["type"] == "image_url", img
    assert img["image_url"]["url"].startswith("data:image/png;base64,"), img

    # 2) 파일 없는 경로는 건너뜀
    content = task_facade.build_user_content("g", images=[missing, png])
    assert [c["type"] for c in content] == ["text", "image_url"], content

    # 3) images 없으면 기존 문자열 그대로(회귀 방지)
    content = task_facade.build_user_content("goal")
    assert isinstance(content, str) and content == "goal", content

    # 4) plan + images → text에 plan 포함
    content = task_facade.build_user_content("g", plan="1. 분석", images=[png])
    assert "[상위 에이전트가 제공한 계획]" in content[0]["text"], content

    # 5) 확장자로 mime 추정(jpeg)
    content = task_facade.build_user_content("g", images=[jpg])
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"), content

    # 6) run()의 has_image 판정과 일치하는지 확인(기존 vision 통합 조건)
    from app.runtime.agent import _has_image
    content = task_facade.build_user_content("g", images=[png])
    assert _has_image({"role": "user", "content": content}) is True
    content = task_facade.build_user_content("g")
    assert _has_image({"role": "user", "content": content}) is False

    print("task_facade 멀티모달 메시지 구성 테스트 통과 ✓")


main()
