"""Bounded dependency-aware scheduling — 병렬 worker 배정 시 파일 소유권 충돌 방지.

P4 시드. 전체 sub-agent 시스템이 아니라 "같은 파일을 동시에 고치지 않는다"는 invariant를
결정적으로 지키는 순수 함수다. worker 수·recursion은 bounded(기본 max_parallel=2).

workers: [{id, files: [상대경로...]}]. 반환: [[worker_id...] ...] — 배치 순서는 입력 순서,
같은 배치 안의 worker들은 파일을 공유하지 않는다(동시 실행 안전). 파일을 공유하는 worker는
다음 배치로 밀린다(순차화). 파일을 선언하지 않은 worker는 어느 배치에나 들어갈 수 있다.
"""


def plan_schedule(workers: list[dict], max_parallel: int = 2) -> list[list]:
    batches: list[list] = []
    current: list = []
    current_files: set = set()
    for w in workers:
        files = set(w.get("files") or [])
        # 파일 충돌이면 현재 배치를 닫고 새 배치에서 시작(순차화).
        if current_files & files:
            if current:
                batches.append(current)
                current = []
                current_files = set()
        current.append(w.get("id"))
        current_files |= files
        if len(current) >= max_parallel:
            batches.append(current)
            current = []
            current_files = set()
    if current:
        batches.append(current)
    return batches


def conflicts(workers: list[dict], max_parallel: int = 2) -> list[tuple]:
    """plan_schedule이 지키는 invariant 검증용 — 같은 배치 내 파일 공유 쌍을 반환한다."""
    out: list[tuple] = []
    for batch in plan_schedule(workers, max_parallel):
        by_id = {w.get("id"): set(w.get("files") or []) for w in workers
                 if w.get("id") in batch}
        ids = list(by_id)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                if by_id[ids[i]] & by_id[ids[j]]:
                    out.append((ids[i], ids[j]))
    return out
