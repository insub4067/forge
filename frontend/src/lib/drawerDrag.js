// 세션 드로어 스와이프 드래그 순수 함수 — App.vue(main 열기)·RoomsPanel.vue(overlay 닫기) 공용
export const DRAWER_THRESHOLD = 0.4 // 이 비율 이상 드래그하면 열림 확정
const DRAWER_MAX_W = 360 // 드로어 최대 폭(px)

// 모바일 드로어 실제 폭: 화면의 86%, 최대 360px
export function drawerWidth(viewportW) {
  return Math.min((viewportW || 0) * 0.86, DRAWER_MAX_W)
}

function clamp01(v) {
  return v <= 0 ? 0 : v >= 1 ? 1 : v
}

// 오른쪽 스와이프(dx>0) → 닫힘→열림 드래그 비율 (0~1, 1=완전히 열림)
export function openRatio(dx, viewportW) {
  const w = drawerWidth(viewportW)
  return w <= 0 ? 0 : clamp01(dx / w)
}

// 왼쪽 스와이프(dx<0) → 열림→닫힘 드래그 비율 (0~1, 1=열림 유지)
export function closeRatio(dx, viewportW) {
  const w = drawerWidth(viewportW)
  return w <= 0 ? 1 : clamp01(1 + dx / w)
}

// 드래그 종료 판정: 임계 비율 이상이면 열림
export function decideOpen(ratio, threshold = DRAWER_THRESHOLD) {
  return ratio >= threshold
}

// 첫 이동 방향 판정: 세로 스크롤과 구분. 아직 모름=null, 가로=true, 세로=false
export function horizontalIntent(dx, dy, dead = 10) {
  if (Math.abs(dx) < dead && Math.abs(dy) < dead) return null
  return Math.abs(dx) > Math.abs(dy)
}
