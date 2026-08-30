import { test } from 'node:test'
import assert from 'node:assert/strict'
import { countGates, gateWarnings } from './gates.js'

const g = (status, o = {}) => ({ title: 't', status, ...o })

test('countGates: passed 외에는 전부 미검증으로 센다', () => {
  const c = countGates([g('passed'), g('failed'), g('unavailable'), g('pending'), g('blocked')])
  assert.deepEqual(c, { passed: 1, failed: 1, unverified: 3, total: 5 })
})

test('countGates: 빈 목록·null도 0으로 (검증 없음을 통과로 뭉개지 않는다)', () => {
  assert.deepEqual(countGates([]), { passed: 0, failed: 0, unverified: 0, total: 0 })
  assert.deepEqual(countGates(null), { passed: 0, failed: 0, unverified: 0, total: 0 })
})

test('gateWarnings: 실패·미검증만 경고로, passed는 제외', () => {
  const w = gateWarnings([
    g('passed', { title: '통과한 것' }),
    g('failed', { title: '깨진 것', failure_reason: '테스트 3건 실패' }),
    g('unavailable', { title: '못 돌린 것' }),
  ])
  assert.equal(w.length, 2)
  assert.deepEqual(w[0], { kind: '실패', title: '깨진 것', reason: '테스트 3건 실패' })
  assert.equal(w[1].kind, '미검증')
  assert.equal(w[1].reason, '독립 검증을 수행하지 못했습니다.')   // 사유 없으면 기본 문구
})

test('gateWarnings: 실행 오류를 뒤에 덧붙인다', () => {
  const w = gateWarnings([g('passed')], ['ENOENT: a.py', 'timeout'])
  assert.equal(w.length, 2)
  assert.deepEqual(w.map((x) => x.kind), ['오류', '오류'])
  assert.equal(w[0].reason, 'ENOENT: a.py')
})

test('gateWarnings: 인자가 없어도 빈 배열', () => {
  assert.deepEqual(gateWarnings(), [])
  assert.deepEqual(gateWarnings(null, null), [])
})
