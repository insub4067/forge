# Acceptance Gate Coverage Enforcement

> 상태: Proposal (2026-08-24)
> 목표: 완료 판정의 근거인 acceptance gate가 **모델 재량**으로 남아 있는 구멍을 닫는다.
> gate가 하나도 없는 작업이 `completed`로 끝나는 경로를 계측하고, 최종적으로 차단한다.

## 발견 (실측)

격리 워크스페이스에서 프로브 세션을 돌려 최근 변경(P0·완료 리포트·프로젝트 메모리)의
end-to-end 동작을 확인하던 중 나왔다.

프로브: 작은 git 저장소(`calc.py` + `test_calc.py`, 로컬 bare origin), 지시는
"sub(a,b) 함수와 그 테스트를 추가해라". 결과:

```
agent_mode  {"mode":"single","complexity":"simple"}
verify_start {"checks":["pytest"]}
autocommit   {"committed":true,"pushed":true}
done         {"status":"completed",
              "content":"완료했습니다.\n검증: 테스트·빌드 통과\n변경 2개 파일 · commit·push 완료"}
```

`GET /api/sessions/{id}/gates` → `[]`. **gate가 하나도 만들어지지 않았다.**

`docs/agents/developer.md`는 "구현을 시작하기 **전에** `update_gates`로 분해해 등록한다"고
명시하고, `update_gates` 도구 설명도 같은 말을 한다. 모델(deepseek flash)이 그냥 건너뛰었다.
프로세스에는 이를 강제하거나 감지하는 장치가 없다.

## 왜 문제인가 (헌법 North Star)

완료 판정 권한은 프로세스가 갖는다는 것이 KPI `false_completion_rate ≈ 0`의 근거다. 그런데
그 판정의 재료인 gate를 **모델이 만들지 안 만들지 결정한다.** gate가 없으면
`_verify_gates`는 `none`을 돌려주고, 완료는 generic verify(repo의 pytest/build 통과) 하나로
결정된다.

generic verify는 "저장소의 기존 테스트가 깨지지 않았다"만 말한다. **사용자의 요구사항이
충족됐는지는 전혀 확인하지 않는다.** 프로브에서 모델이 sub를 구현하지 않고 무관한 주석만
넣었어도 기존 테스트는 통과하고 `completed`가 났을 것이다. 이것이 정확히 false completion이다.

즉 gate 미생성은 "기능 하나가 안 쓰인 것"이 아니라 **완료 판정 체계의 우회 경로**다.

## 표본 (과장하지 않기)

gate 기능은 `2f48342`(2026-08-24 08:53 KST = 23:53 UTC 08-23)에 들어갔다. 그 이후 이벤트
로그에서 실제로 파일을 바꾼 세션은 2개뿐이다.

| 세션 | 편집 | gates_update | done |
|---|---|---|---|
| `980518c2` (복합 작업, 요구사항 다수) | 11 | 17 | completed ×2, **verification_failed** ×1 |
| `9c545725` (프로브, simple) | 2 | 0 | completed |

**표본 2개다. 비율을 주장할 수 없다.** 말할 수 있는 것은 두 가지다.

1. 메커니즘은 호출되면 작동한다 — `980518c2`에서 gate가 실제로 `verification_failed`를
   띄워 완료를 막았다. 설계는 유효하다.
2. 호출 여부가 모델 재량이고, 최소 1건(simple 작업)에서 건너뛰어졌다. 프로세스는 그것을
   감지도 기록도 하지 않았다.

이 두 번째가 이 proposal의 대상이다. **얼마나 자주 일어나는지는 아직 모른다 — 그것부터
알아야 한다.**

## 설계 (단계적, 계측 먼저)

### G0 — 계측 (먼저, 무해)

완료 시 gate 커버리지를 이벤트·메트릭으로 남긴다. 동작은 바꾸지 않는다.

- `finish`에서 `gate_coverage` 이벤트: `{gates: n, passed: m, generic_only: bool}`.
- `generic_only=true`(gate 0개인데 completed)를 세션 메트릭에 집계.
- 며칠 실사용 후 실제 빈도를 읽는다.

계측을 먼저 두는 이유: 강제 규칙을 지금 넣으면 정상 작업까지 막을 수 있고, 얼마나 흔한
문제인지 모른 채 설계 결정을 하게 된다.

### G1 — 정직 표기 (G0과 함께 가능)

gate 0개로 완료한 run의 리포트가 "완료했습니다 / 검증: 테스트·빌드 통과"로 끝나 완전히
검증된 것처럼 읽힌다. 요구사항 검증이 없었다는 사실을 리포트에 남긴다.

```
완료했습니다.
검증: 테스트·빌드 통과 (기존 테스트 회귀만 — 요구사항 게이트 없음)
```

기존 `_gates_report`가 gate 0개면 빈 문자열을 돌려주는데, 그 침묵이 곧 오해다.
honest failure 원칙의 연장이다.

### G2 — 강제 (G0 계측 결과를 보고 결정)

gate 0개인 채로 구현이 끝나면 완료를 내주지 않고 한 번 되돌린다. 선택지:

- **(a) 재요청**: gate 없이 완료 시도 → "요구사항을 update_gates로 등록하라"를 1회 주입하고
  루프 계속. 비용 1스텝. 모델이 두 번째도 안 하면 G1 표기로 완료.
- **(b) 프로세스 합성**: 사용자 요청에서 프로세스가 gate를 1개 만든다. 검증 방법을 안전하게
  합성하기 어렵다 — 잘못된 gate는 잘못된 통과를 만든다. 위험하다.
- **(c) 완료 거부**: gate 0개면 `completed` 불가, `completed_unverified` 고정. 가장 엄격하지만
  진짜로 gate가 부적절한 작업(문서 수정, 탐색)까지 걸린다.

현재 선호: **(a)**. 비용이 1스텝이고, 실패해도 G1로 정직하게 떨어진다. (b)는 프로세스가
검증을 지어내는 것이라 헌법에 어긋난다. (c)는 G0 데이터가 "거의 항상 gate가 없다"로 나올
때만 고려한다.

`complexity=simple` 분기에서 gate를 면제할지도 G0 데이터로 판단한다. 지금은 면제 로직이
없고 — 프로브가 simple로 분류돼 gate 없이 끝난 것은 분류 때문이 아니라 모델이 안 불렀기
때문이다.

## 범위 밖

- gate 품질(검증 방법이 실제로 요구사항을 검증하는가)은 별개 문제다. `66e1572`에서
  `grep -q` false-fail 지침을 이미 강화했다.
- Reviewer fresh context, provider 독립 등 다른 P1/P2 항목과 무관하게 진행 가능하다.

## 검증 기준

- G0: 프로브 세션 2종(gate 있는 작업 / 없는 작업)에서 `gate_coverage` 이벤트가 각각
  올바른 값으로 나온다.
- G1: gate 0개 완료 리포트에 "요구사항 게이트 없음"이 포함된다. 단위 테스트로 고정.
- G2: gate 없이 완료 시도한 run이 재요청을 1회 받고, 두 번째도 없으면 G1 표기로 끝난다.
