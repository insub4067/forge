"""태스크 신원 유지 회귀 테스트 (DB·LLM 없음 — 순수 병합 로직).

중복 표시의 원인이었던 것: 모델이 매번 전체 목록을 다시 보내면서 같은 태스크의 제목을
조금씩 고쳐 쓴다("A" → "A (이미 구현·테스트 완료)"). 제목을 신원으로 쓰면 같은 태스크가
새 태스크로 다시 생겨 목록·요약이 중복된다.

실행: python test_task_identity.py  (pytest로도 수집된다)
"""
from app.db.store import merge_tasks, task_key


def _existing(*rows):
    return [{"id": i + 1, "title": t, "status": s, "progress": 0}
            for i, (t, s) in enumerate(rows)]


def test_key_ignores_parenthetical_annotation():
    assert task_key("폴더 순환 구조 방지") == task_key("폴더 순환 구조 방지 (이미 구현·테스트 완료)")
    assert task_key("관리자 TTS 동시성 제한(세마포어)") == task_key("관리자 TTS 동시성 제한 (이미 DOC 반영)")
    assert task_key("A") != task_key("B")


def test_retitled_task_keeps_identity_and_title():
    existing = _existing(("폴더 순환 구조 방지", "working"))
    merged = merge_tasks(existing, [
        {"title": "폴더 순환 구조 방지 (이미 구현·테스트 완료)", "status": "working"},
    ])
    assert len(merged) == 1                     # 새 태스크가 생기지 않는다
    assert merged[0]["id"] == 1                 # 신원 유지
    assert merged[0]["title"] == "폴더 순환 구조 방지"  # 표시 제목도 흔들리지 않는다


def test_status_change_does_not_duplicate():
    existing = _existing(("A 작업 구현", "todo"), ("B 작업 검증", "todo"))
    merged = merge_tasks(existing, [
        {"title": "A 작업 구현", "status": "working"},
        {"title": "B 작업 검증", "status": "todo"},
    ])
    assert [m["id"] for m in merged] == [1, 2]
    assert merged[0]["status"] == "working"


def test_full_lifecycle_keeps_one_identity():
    tasks = [{"title": "동시성 제한 구현", "status": "todo"}]
    existing = merge_tasks([], tasks)
    existing = [{**m, "id": 7} for m in existing]          # 저장됐다고 가정
    for status in ("working", "testing", "done"):
        merged = merge_tasks(existing, [{"title": "동시성 제한 구현", "status": status}])
        assert len(merged) == 1 and merged[0]["id"] == 7, (status, merged)
        existing = merged


def test_duplicate_in_one_payload_is_collapsed():
    merged = merge_tasks([], [
        {"title": "관리자 TTS 동시성 제한", "status": "working"},
        {"title": "관리자 TTS 동시성 제한 (세마포어)", "status": "todo"},
    ])
    assert len(merged) == 1 and merged[0]["status"] == "working"


def test_replay_of_older_payload_does_not_duplicate():
    # reconnect 후 예전 이벤트가 다시 재생돼도 태스크가 늘어나지 않는다(상태만 되돌아감).
    existing = _existing(("A 작업 구현", "testing"), ("B 작업 검증", "testing"))
    merged = merge_tasks(existing, [
        {"title": "A 작업 구현", "status": "working"},
        {"title": "B 작업 검증", "status": "todo"},
    ])
    assert [m["id"] for m in merged] == [1, 2]


def test_new_task_added_and_dropped_task_removed():
    existing = _existing(("A 작업 구현", "done"), ("B 작업 검증", "todo"))
    merged = merge_tasks(existing, [
        {"title": "A 작업 구현", "status": "done"},
        {"title": "C 새 작업 추가", "status": "todo"},
    ])
    assert [m["id"] for m in merged] == [1, None]
    assert merged[1]["title"] == "C 새 작업 추가"


def test_short_titles_do_not_false_match():
    existing = _existing(("배포", "todo"))
    merged = merge_tasks(existing, [{"title": "배포 검증 자동화", "status": "todo"}])
    assert merged[0]["id"] is None              # 5자 이하 접두 오매칭 금지


def test_progress_is_kept_when_omitted():
    existing = [{"id": 3, "title": "A 작업 구현", "status": "working", "progress": 60}]
    merged = merge_tasks(existing, [{"title": "A 작업 구현", "status": "working"}])
    assert merged[0]["progress"] == 60


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: OK")
    print("\n태스크 신원 유지 통과 ✓")
