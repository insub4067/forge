// 실행: cd frontend && node --test src/lib/drawerDrag.test.js  (의존성 없음)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isOpenSwipe } from './drawerDrag.js'

test('오른쪽으로 충분히 스와이프하면 열림', () => {
  assert.equal(isOpenSwipe(80, 10), true)
})
test('거리 미달(60px 미만)이면 안 열림', () => {
  assert.equal(isOpenSwipe(40, 10), false)
  assert.equal(isOpenSwipe(60, 0), false) // 경계값: 초과해야 열림
})
test('왼쪽 스와이프는 안 열림', () => {
  assert.equal(isOpenSwipe(-80, 10), false)
})
test('세로 이동이 우세하면 안 열림(스크롤 보호)', () => {
  assert.equal(isOpenSwipe(70, 60), false)
})
test('세로/가로 동일 이동이면 안 열림', () => {
  assert.equal(isOpenSwipe(50, 50), false)
})
test('약간의 세로 흔들림은 허용', () => {
  assert.equal(isOpenSwipe(100, 40), true) // 100 > 40*1.4=56
})
test('사용자 지정 임계값 적용', () => {
  assert.equal(isOpenSwipe(80, 10, { minDx: 100 }), false)
  assert.equal(isOpenSwipe(120, 10, { minDx: 100 }), true)
})
