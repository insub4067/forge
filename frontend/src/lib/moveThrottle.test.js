// 실행: node --test src/lib/moveThrottle.test.js   (frontend/ 에서, 의존성 없음)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { makeMoveThrottle } from './moveThrottle.js'

test('첫 이벤트는 즉시 보낸다', () => {
  const sent = []
  const t = makeMoveThrottle((p) => sent.push(p), 40, () => 1000)
  t({ x: 1, y: 1 })
  assert.deepEqual(sent, [{ x: 1, y: 1 }])
})

test('주기 안의 연속 이벤트는 한 번으로 합친다', async () => {
  const sent = []
  let clock = 1000
  const t = makeMoveThrottle((p) => sent.push(p), 40, () => clock)
  t({ x: 1, y: 1 })
  for (let i = 2; i <= 20; i++) t({ x: i, y: i })
  assert.equal(sent.length, 1, '주기 안에서는 leading 1건만 나가야 한다')
  await new Promise((r) => setTimeout(r, 60))
  assert.equal(sent.length, 2, 'trailing 1건이 더 나가야 한다')
})

test('마지막 좌표를 보낸다 — 커서가 멈춘 자리에 남아야 한다', async () => {
  const sent = []
  const t = makeMoveThrottle((p) => sent.push(p), 40, () => 1000)
  t({ x: 1, y: 1 })
  t({ x: 5, y: 5 })
  t({ x: 9, y: 9 })
  await new Promise((r) => setTimeout(r, 60))
  assert.deepEqual(sent[sent.length - 1], { x: 9, y: 9 })
})

test('주기가 지난 뒤의 이벤트는 다시 즉시 나간다', () => {
  const sent = []
  let clock = 1000
  const t = makeMoveThrottle((p) => sent.push(p), 40, () => clock)
  t({ x: 1, y: 1 })
  clock += 50
  t({ x: 2, y: 2 })
  assert.deepEqual(sent, [{ x: 1, y: 1 }, { x: 2, y: 2 }])
})
