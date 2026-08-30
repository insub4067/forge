// 현재 세션의 프로세스 산출물 — 칸반(tasks)·검증 게이트(gates)·개선안(refinements).
// 방 식별자는 인자로 받는다(rooms 상태에 의존하지 않게). App.vue가 얇은 래퍼로 넘긴다.
import { ref } from 'vue'
import { countGates, gateWarnings } from '../lib/gates.js'

export const tasks = ref([])
export const gates = ref([])   // Acceptance Gate — 요구사항별 검증 상태(passed는 프로세스 소유)
export const refinements = ref([])

export async function loadTasks(roomId) {
  if (!roomId) { tasks.value = []; return }
  try {
    const res = await fetch(`/api/rooms/${roomId}/tasks`)
    if (res.ok) tasks.value = await res.json()
  } catch {}
}

export async function loadGates(roomId) {
  if (!roomId) { gates.value = []; return }
  try {
    const res = await fetch(`/api/sessions/${roomId}/gates`)
    if (res.ok) gates.value = await res.json()
  } catch {}
}

export async function loadRefinements(roomId) {
  if (!roomId) { refinements.value = []; return }
  try {
    const res = await fetch(`/api/rooms/${roomId}/refinements`)
    if (res.ok) refinements.value = (await res.json()).refinements || []
  } catch {}
}

export async function decideRefinement(r, decision, roomId) {
  try {
    await fetch(`/api/refinements/${r.id}/decide`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    })
    await loadRefinements(roomId)
  } catch {}
}

export function verifyCounts() {
  return countGates(gates.value)
}

export function resultWarnings(m) {
  return gateWarnings(gates.value, m.state?.errors)
}
