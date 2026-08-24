// 고빈도 포인터 이벤트를 일정 주기로 줄인다. mousemove는 트랙패드에서 100Hz를 넘기고,
// 이벤트마다 /api/mac/input POST가 나가면 host가 입력 폭주로 밀린다.
//
// 중간 좌표는 버리고 최신 것만 남기되, **마지막 좌표는 반드시 보낸다** — 사용자가 멈춘
// 자리에 커서가 남아야 한다. leading edge만 있는 throttle은 커서를 엉뚱한 데 두고 끝난다.
export function makeMoveThrottle(send, ms = 40, now = () => Date.now()) {
  let lastSent = 0
  let pending = null
  let timer = null
  return function throttled(point) {
    const wait = ms - (now() - lastSent)
    if (wait <= 0) {
      lastSent = now()
      pending = null
      send(point)
      return
    }
    pending = point
    if (timer) return
    timer = setTimeout(() => {
      timer = null
      if (!pending) return
      lastSent = now()
      const p = pending
      pending = null
      send(p)
    }, wait)
  }
}
