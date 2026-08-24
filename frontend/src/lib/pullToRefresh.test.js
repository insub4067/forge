// 실행: cd frontend && node --test src/lib/pullToRefresh.test.js  (의존성 없음)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { pullDistance, pullReady, PULL } from './pullToRefresh.js'

test('위로 당기면(또는 안 움직이면) 거리 0 — 정상 스크롤', () => {
  assert.equal(pullDistance(0), 0)
  assert.equal(pullDistance(-50), 0)
})

test('아래로 당기면 감쇠가 적용된다(고무줄)', () => {
  assert.equal(pullDistance(40, { threshold: 64, maxPull: 96, damp: 0.5 }), 20)
})

test('당김은 maxPull로 잘린다', () => {
  assert.equal(pullDistance(1000, PULL), PULL.maxPull)
})

test('threshold를 넘겨야 새로고침 준비', () => {
  // 손가락 128px → 거리 64px == threshold → ready
  assert.equal(pullReady(pullDistance(128, PULL), PULL), true)
  // 손가락 100px → 거리 50px < 64 → not ready
  assert.equal(pullReady(pullDistance(100, PULL), PULL), false)
})
