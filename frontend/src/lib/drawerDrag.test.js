// 실행: cd frontend && node --test src/lib/drawerDrag.test.js  (의존성 없음)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { drawerWidth, openRatio, closeRatio, decideOpen, horizontalIntent } from './drawerDrag.js'

test('drawerWidth: 375px 뷰포트는 86%', () => {
  assert.ok(Math.abs(drawerWidth(375) - 322.5) < 1e-9)
})
test('drawerWidth: 넓은 뷰포트는 360px 캡', () => {
  assert.equal(drawerWidth(1000), 360)
})
test('drawerWidth: 0 뷰포트는 0', () => {
  assert.equal(drawerWidth(0), 0)
})
test('openRatio: 오른쪽 반쯤 드래그 → 0.5', () => {
  assert.ok(Math.abs(openRatio(161.25, 375) - 0.5) < 1e-9)
})
test('openRatio: 이동 없음 → 0', () => {
  assert.equal(openRatio(0, 375), 0)
})
test('openRatio: 왼쪽 이동(음수)은 0 유지', () => {
  assert.equal(openRatio(-50, 375), 0)
})
test('openRatio: 드로어 폭 초과 드래그는 1 캡', () => {
  assert.equal(openRatio(9999, 375), 1)
})
test('closeRatio: 왼쪽 반쯤 드래그 → 0.5', () => {
  assert.ok(Math.abs(closeRatio(-161.25, 375) - 0.5) < 1e-9)
})
test('closeRatio: 오른쪽 이동은 1(열림) 유지', () => {
  assert.equal(closeRatio(30, 375), 1)
})
test('closeRatio: 왼쪽 과다 드래그는 0 캡', () => {
  assert.equal(closeRatio(-9999, 375), 0)
})
test('decideOpen: 0.4 이상이면 열림', () => {
  assert.equal(decideOpen(0.4), true)
  assert.equal(decideOpen(0.39), false)
  assert.equal(decideOpen(1), true)
  assert.equal(decideOpen(0), false)
})
test('horizontalIntent: 미세 이동은 null(미결정)', () => {
  assert.equal(horizontalIntent(3, 3), null)
})
test('horizontalIntent: 가로 우세면 true', () => {
  assert.equal(horizontalIntent(30, 10), true)
})
test('horizontalIntent: 세로 우세면 false', () => {
  assert.equal(horizontalIntent(10, 30), false)
})
