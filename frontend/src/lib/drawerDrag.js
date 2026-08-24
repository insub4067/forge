// 세션 드로어 스와이프 열림 판정 — App.vue(main) 공용 순수 함수
export const SWIPE_MIN_DX = 60 // 오른쪽 스와이프 최소 거리(px)
export const SWIPE_RATIO = 1.4 // 가로/세로 우세 판정 배수

// 오른쪽 스와이프로 드로어 열기 판정:
// 가로로 충분히 멀리 움직였고(60px 이상), 세로 이동보다 뚜렷하게 우세해야 한다(1.4배).
export function isOpenSwipe(dx, dy, opts = {}) {
  const minDx = opts.minDx ?? SWIPE_MIN_DX
  const ratio = opts.ratio ?? SWIPE_RATIO
  return dx > minDx && Math.abs(dx) > Math.abs(dy) * ratio
}
