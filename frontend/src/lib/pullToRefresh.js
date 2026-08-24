// 풀투리프레시 제스처의 핵심 계산(프레임워크·의존성 없음).
//
// 스크롤 최상단에서 아래로 당기면 새로고침한다. 가로 스와이프(아이템 삭제)와 축이 달라
// 충돌하지 않는다 — 이 계산은 세로 당김 거리만 다룬다. DOM/touch 바인딩은 컴포넌트가 한다.
//
// 고무줄 느낌: 손가락 이동(dy)에 감쇠를 곱하고 상한으로 자른다. threshold를 넘겨 놓으면
// 새로고침이 발동한다.
export const PULL = { threshold: 64, maxPull: 96, damp: 0.5 }

// 손가락이 dy만큼 내려갔을 때 실제로 보여줄 당김 거리(px). 위로 가면(dy<=0) 0 — 정상 스크롤.
export function pullDistance(dy, o = PULL) {
  if (dy <= 0) return 0
  return Math.min(o.maxPull, dy * o.damp)
}

// 놓았을 때 새로고침을 발동할 만큼 충분히 당겼는가.
export function pullReady(distance, o = PULL) {
  return distance >= o.threshold
}
