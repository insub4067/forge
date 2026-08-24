// 실행: node --test src/lib/screenCoord.test.js   (frontend/ 에서, 의존성 없음)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { toScreenXY } from './screenCoord.js'

test('비회전: 표시 좌표를 원본으로 비례 변환', () => {
  const p = toScreenXY(
    { clientX: 100, clientY: 80 },
    { left: 0, top: 0, width: 200, height: 160 },
    { w: 800, h: 600 }, false,
  )
  assert.deepEqual(p, { x: 400, y: 300 })
})

test('회전(portrait): rotate(90deg) 역보정 — 표시 중앙이 원본 중앙', () => {
  const p = toScreenXY(
    { clientX: 150, clientY: 50 },
    { left: 0, top: 0, width: 300, height: 100 },
    { w: 1000, h: 600 }, true,
  )
  assert.deepEqual(p, { x: 500, y: 300 })
})

test('회전: 표시 우상단이 원본 좌상단(0,0)으로 매핑', () => {
  const p = toScreenXY(
    { clientX: 300, clientY: 0 },
    { left: 0, top: 0, width: 300, height: 100 },
    { w: 1000, h: 600 }, true,
  )
  assert.deepEqual(p, { x: 0, y: 0 })
})

test('회전: 표시 우하단이 원본 우상단(가로 끝)으로 매핑', () => {
  const p = toScreenXY(
    { clientX: 300, clientY: 100 },
    { left: 0, top: 0, width: 300, height: 100 },
    { w: 1000, h: 600 }, true,
  )
  assert.deepEqual(p, { x: 1000, y: 0 })
})

test('이미지 밖 좌표는 원본 범위로 클램프', () => {
  const p = toScreenXY(
    { clientX: 9999, clientY: -50 },
    { left: 0, top: 0, width: 200, height: 160 },
    { w: 800, h: 600 }, false,
  )
  assert.deepEqual(p, { x: 800, y: 0 })
})

test('자연 크기 정보가 없으면 null', () => {
  const p = toScreenXY({ clientX: 1, clientY: 1 }, { left: 0, top: 0, width: 200, height: 160 }, { w: 0, h: 0 })
  assert.equal(p, null)
})
