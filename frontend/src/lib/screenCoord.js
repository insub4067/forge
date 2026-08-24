// 표시된 화면 이미지 좌표 → 원본 캡처 좌표 변환.
//
// portrait(세로)에서는 CSS가 이미지를 rotate(90deg)로 회전 표시하므로(
// .mac-overlay.is-screen .mac-screen-video) 그 경우 회전 보정이 필요하다.
// 회전 표시 박스는 width=원본 세로, height=원본 가로가 된다.
//
// object-fit: contain으로 표시될 때, 요소 bounding box 안에서 이미지가 실제로
// 차지하는 영역(content box)을 계산한다. 레터박스(여백)를 무시하고 좌표를 비례
// 변환하려면 toScreenXY에 이 content box를 넘겨야 한다.
// 회전(rotate 90°) 표시에서는 bounding box의 가로에 원본 세로(H), 세로에 원본
// 가로(W)가 대응하므로 스케일 계산 기준 축을 바꾼다.
export function containContentRect(rect, natural, rotated = false) {
  if (!rect || !natural || !natural.w) return null
  const W = natural.w
  const H = natural.h
  let cw, ch
  if (rotated) {
    const scale = Math.min(rect.width / H, rect.height / W)
    cw = H * scale
    ch = W * scale
  } else {
    const scale = Math.min(rect.width / W, rect.height / H)
    cw = W * scale
    ch = H * scale
  }
  return {
    left: rect.left + (rect.width - cw) / 2,
    top: rect.top + (rect.height - ch) / 2,
    width: cw,
    height: ch,
  }
}

// rotate(90deg) 시계방향 역변환:
//   u(원본 가로) = clientY - rect.top
//   v(원본 세로) = rect.left + rect.width - clientX
export function toScreenXY(ev, rect, natural, rotated = false) {
  if (!rect || !natural || !natural.w) return null
  const W = natural.w
  const H = natural.h
  let sx, sy
  if (rotated) {
    const u = ev.clientY - rect.top
    const v = rect.left + rect.width - ev.clientX
    sx = (u / rect.height) * W
    sy = (v / rect.width) * H
  } else {
    sx = ((ev.clientX - rect.left) / rect.width) * W
    sy = ((ev.clientY - rect.top) / rect.height) * H
  }
  return {
    x: Math.round(Math.min(W, Math.max(0, sx))),
    y: Math.round(Math.min(H, Math.max(0, sy))),
  }
}
