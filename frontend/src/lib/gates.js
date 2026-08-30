// 검증 게이트 집계·경고 변환 — 상태(ref)를 참조하지 않는 순수 함수.
// 완료 판정을 왜곡하지 않는 것이 핵심이라 단위 테스트로 고정한다(gates.test.js).

// passed 외에는 모두 '미검증'으로 센다(unavailable·pending·blocked 등).
// 미검증을 통과로 뭉뚱그리면 화면이 실제보다 검증된 것처럼 보인다.
export function countGates(list) {
  const g = list || []
  let passed = 0, failed = 0, unverified = 0
  for (const x of g) {
    if (x.status === 'passed') passed++
    else if (x.status === 'failed') failed++
    else unverified++
  }
  return { passed, failed, unverified, total: g.length }
}

// 실패·미검증 게이트 + 실행 오류를 경고 카드 목록으로. 사유를 함께 담는다.
export function gateWarnings(list, errors) {
  const out = []
  for (const g of (list || [])) {
    if (g.status === 'failed') out.push({ kind: '실패', title: g.title, reason: g.failure_reason || '검증에 실패했습니다.' })
    else if (g.status !== 'passed') out.push({ kind: '미검증', title: g.title, reason: g.failure_reason || '독립 검증을 수행하지 못했습니다.' })
  }
  for (const e of (errors || [])) out.push({ kind: '오류', title: '실행 오류', reason: String(e) })
  return out
}
