import { ref } from 'vue'

// 충전 잔액 전역 상태 — 앱 실행 시 최초 1회 fetch하고 모든 패널이 공유한다.
export const balance = ref(null)

let _fetching = null // 진행 중이면 같은 Promise 재사용 → 중복 fetch 방지

export function loadBalance() {
  // 이미 값이 있거나 fetch가 진행 중이면 재요청하지 않는다(실패 시 다음 호출에서 재시도).
  if (balance.value || _fetching) return _fetching
  _fetching = fetch('/api/admin/balance')
    .then((res) => (res.ok ? res.json() : null))
    .then((data) => {
      if (data) balance.value = data
    })
    .catch(() => {})
    .finally(() => { _fetching = null })
  return _fetching
}
