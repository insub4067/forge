<script setup>
// 알림·기기 패널 — 웹 푸시 등록/해지/테스트를 관리한다.
// App.vue의 showPush 관련 상태·함수·마크업을 이 컴포넌트로 이관.
import { ref, onMounted } from 'vue'

const emit = defineEmits(['close'])

const pushDevices = ref([])
const pushSupported = 'serviceWorker' in navigator && 'PushManager' in window

async function loadDevices() {
  try {
    const res = await fetch('/api/push/devices')
    if (res.ok) pushDevices.value = (await res.json()).devices || []
  } catch {}
}

function urlB64ToUint8(base64) {
  const pad = '='.repeat((4 - (base64.length % 4)) % 4)
  const b64 = (base64 + pad).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(b64)
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
}

async function enablePush() {
  if (!pushSupported) { alert('이 기기는 웹 푸시를 지원하지 않습니다.'); return }
  try {
    const perm = await Notification.requestPermission()
    if (perm !== 'granted') { alert('알림 권한이 거부되었습니다.'); return }
    const reg = await navigator.serviceWorker.ready
    const { public_key } = await (await fetch('/api/push/vapid-public')).json()
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlB64ToUint8(public_key),
    })
    await fetch('/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: navigator.platform || '기기', subscription: sub.toJSON() }),
    })
    await loadDevices()
  } catch (e) {
    alert('알림 설정 실패: ' + (e.message || e))
  }
}

async function deleteDevice(id) {
  try {
    await fetch(`/api/push/devices/${id}`, { method: 'DELETE' })
    await loadDevices()
  } catch {}
}

async function testPush() {
  try { await fetch('/api/push/test', { method: 'POST' }) } catch {}
}

onMounted(loadDevices)
</script>

<template>
  <div class="kanban-overlay">
    <div class="kanban-head">
      <span class="kanban-title">알림 · 기기</span>
      <button @click="emit('close')">닫기</button>
    </div>
    <div class="admin-body">
      <div class="admin-section">
        <div class="admin-stat-title">작업 완료 알림</div>
        <div class="admin-sub">이 기기를 등록하면 일반 작업과 예약 작업이 끝날 때 푸시 알림을 받습니다.</div>
        <div class="push-actions">
          <button class="detail-link" @click="enablePush">＋ 이 기기 알림 켜기</button>
          <button v-if="pushDevices.length" class="detail-link" @click="testPush">테스트 알림 보내기</button>
        </div>
        <div v-if="!pushSupported" class="metric-warn">⚠ 이 기기/브라우저는 웹 푸시를 지원하지 않습니다(iOS는 홈화면 추가 PWA에서만 가능).</div>
      </div>
      <div class="admin-section">
        <div class="admin-stat-title">등록된 기기 {{ pushDevices.length }}</div>
        <div v-for="d in pushDevices" :key="d.id" class="admin-row">
          <span>{{ d.name || '기기' }} <span class="run-count">{{ (d.created_at || '').slice(0, 10) }}</span></span>
          <button class="skill-del" @click="deleteDevice(d.id)">해지</button>
        </div>
        <div v-if="!pushDevices.length" class="admin-sub">등록된 기기가 없습니다.</div>
      </div>
    </div>
  </div>
</template>
