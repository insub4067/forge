<script setup>
// 세션 상세 패널 — 컨텍스트·토큰·비용·에이전트/모델별 사용량·실행 이력.
// App.vue의 showSessionDetail 관련 상태·함수·마크업을 이 컴포넌트로 이관.
import { ref, nextTick, onMounted } from 'vue'
import html2canvas from 'html2canvas'
import { balance as adminBalance, loadBalance } from '../store'

const props = defineProps({
  roomId: { type: String, default: '' },
  roomTitle: { type: String, default: '세션' },
  room: { type: Object, default: null },
})
const emit = defineEmits(['close', 'top-up'])

const ROLE_LABELS = {
  triage: '분류',
  developer: '개발',
  chat: '응답',
  vision: '이미지 분석',
}

const sessionRuns = ref([])
const sessionMetrics = ref(null)
const ctxBreakdown = ref(null)  // 마지막 LLM 호출의 context 영역 분해(debug view)
const toolUsage = ref([])  // 도구별 호출 횟수(어떤 툴 몇 번)
const CTX_LABELS = { system_base_role: 'System·규칙', memory: '메모리', skills: 'Skills', history_content: '대화', tool_results: '도구 결과', reasoning_content: '추론', tool_call_arguments: '도구 인자' }
const showRunHistory = ref(false)
const capturing = ref(false)
const panelEl = ref(null)   // 캡처 대상: 패널 프레임(헤더+본문)
const bodyEl = ref(null)    // 스크롤 컨테이너 — 캡처 동안 제약을 풀어 전체 길이를 담는다

// 전체 페이지(긴 내용까지) 스크린샷 — DOM을 html2canvas로 통째로 래스터화한다.
// getDisplayMedia는 iOS PWA(standalone)에서 "화면 녹화" 권한 프롬프트만 띄우고 폰 화면만
// 잡혀 쓸모가 없었다. html2canvas는 권한 없이 스크롤 밖 내용까지 한 장으로 담는다.
// 저장은 iOS에서 다운로드가 막히므로 Web Share(파일 공유)를 먼저 시도하고, 없으면 다운로드.
async function captureScreenshot() {
  if (capturing.value) return
  const panel = panelEl.value
  if (!panel) return
  capturing.value = true
  const body = bodyEl.value
  const saved = body ? { height: body.style.height, maxHeight: body.style.maxHeight, overflow: body.style.overflow } : null
  if (body) { body.style.height = 'auto'; body.style.maxHeight = 'none'; body.style.overflow = 'visible' }
  try {
    await nextTick()
    const bg = getComputedStyle(panel).backgroundColor
    const canvas = await html2canvas(panel, {
      backgroundColor: bg && bg !== 'rgba(0, 0, 0, 0)' ? bg : '#0b0b0d',
      scale: Math.min(2, window.devicePixelRatio || 1),
      useCORS: true,
      windowWidth: panel.scrollWidth,
      windowHeight: panel.scrollHeight,
      height: panel.scrollHeight,
    })
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
    if (!blob) throw new Error('PNG 변환 실패')
    const name = `forge-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.png`
    const file = new File([blob], name, { type: 'image/png' })
    // iOS: 다운로드가 막혀 있어 공유 시트(→ 이미지 저장)가 정석. 지원되면 우선 사용.
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({ files: [file] })
    } else {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = name
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    }
  } catch (err) {
    if (err && err.name !== 'AbortError') {
      alert('스크린샷 실패: ' + (err.message || err))
    }
  } finally {
    if (body && saved) { body.style.height = saved.height; body.style.maxHeight = saved.maxHeight; body.style.overflow = saved.overflow }
    capturing.value = false
  }
}

function formatTokens(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n || 0)
}

function ctxPct(room) {
  const used = room?.used_tokens || 0
  const budget = room?.logical_budget || 262144
  if (!budget) return 0
  return Math.min(100, Math.round((used / budget) * 100))
}

function ctxClass(pct) {
  if (pct >= 95) return 'crit'
  if (pct >= 85) return 'danger'
  if (pct >= 75) return 'warn'
  if (pct >= 60) return 'notice'
  return 'ok'
}

function sessionTokenTotals() {
  let prompt = 0, completion = 0
  for (const r of sessionRuns.value) {
    prompt += r.prompt_tokens || 0
    completion += r.completion_tokens || 0
  }
  return { prompt, completion, total: prompt + completion }
}

function sessionRoleBreakdown() {
  const agg = {}
  for (const r of sessionRuns.value) {
    const k = r.role || '기타'
    if (!agg[k]) agg[k] = { role: k, count: 0, prompt: 0, completion: 0 }
    agg[k].count++
    agg[k].prompt += r.prompt_tokens || 0
    agg[k].completion += r.completion_tokens || 0
  }
  return Object.values(agg)
    .map((a) => ({ ...a, total: a.prompt + a.completion }))
    .sort((a, b) => b.total - a.total)
}

function sessionModelBreakdown() {
  const agg = {}
  for (const r of sessionRuns.value) {
    const k = r.model || 'unknown'
    if (!agg[k]) agg[k] = { model: k, count: 0, prompt: 0, completion: 0 }
    agg[k].count++
    agg[k].prompt += r.prompt_tokens || 0
    agg[k].completion += r.completion_tokens || 0
  }
  return Object.values(agg)
    .map((a) => ({ ...a, total: a.prompt + a.completion }))
    .sort((a, b) => b.total - a.total)
}

onMounted(async () => {
  loadBalance()
  try {
    const res = await fetch(`/api/rooms/${props.roomId}/runs`)
    if (res.ok) sessionRuns.value = await res.json()
    const mres = await fetch(`/api/rooms/${props.roomId}/metrics`)
    if (mres.ok) sessionMetrics.value = await mres.json()
    const cres = await fetch(`/api/sessions/${props.roomId}/context`)
    if (cres.ok) {
      const c = await cres.json()
      if (c && c.areas) ctxBreakdown.value = c
    }
    const tres = await fetch(`/api/sessions/${props.roomId}/tool-usage`)
    if (tres.ok) toolUsage.value = (await tres.json()).tools || []
  } catch {}
})
</script>

<template>
  <div class="kanban-overlay" ref="panelEl">
    <div class="kanban-head">
      <span class="kanban-title">{{ roomTitle }} · 사용량</span>
      <div class="kanban-head-actions">
        <button :disabled="capturing" @click="captureScreenshot">{{ capturing ? '캡처 중…' : '스크린샷' }}</button>
        <button @click="emit('close')">닫기</button>
      </div>
    </div>
    <div class="admin-body" ref="bodyEl">
      <div class="admin-section">
        <div class="admin-stat-title">컨텍스트 윈도우 (최근 호출)</div>
        <div class="admin-big">{{ ctxPct(room) }}%</div>
        <div class="ctx-bar">
          <div class="ctx-bar-fill" :class="ctxClass(ctxPct(room))" :style="{ width: ctxPct(room) + '%' }"></div>
        </div>
        <div class="admin-sub">
          {{ formatTokens(room?.used_tokens) }} / {{ formatTokens(room?.logical_budget) }} tokens
        </div>
      </div>

      <div class="admin-section">
        <div class="admin-stat-title">누적 토큰 (세션 전체)</div>
        <div class="admin-big">{{ formatTokens(sessionTokenTotals().total) }}</div>
        <div class="admin-sub">
          prompt {{ formatTokens(sessionTokenTotals().prompt) }} · completion {{ formatTokens(sessionTokenTotals().completion) }}
        </div>
      </div>

      <div class="admin-section">
        <div class="admin-stat-title">DeepSeek 잔액</div>
        <button class="balance-box" @click="emit('top-up')" aria-label="충전 화면으로 이동">
          <template v-if="adminBalance && adminBalance.ok">
            <div class="admin-big">${{ adminBalance.usd }}</div>
            <div class="admin-sub">
              {{ adminBalance.currency }} {{ adminBalance.total }} · 탭하면 충전 화면으로 이동
            </div>
          </template>
          <div v-else-if="adminBalance && adminBalance.error" class="admin-sub">잔액 조회 실패: {{ adminBalance.error }}</div>
          <div v-else class="admin-sub">잔액 불러오는 중…</div>
        </button>
        <div v-if="sessionMetrics && sessionMetrics.estimated_cost != null" class="admin-row balance-cost">
          <span>이번 세션 비용</span>
          <span class="mono">${{ sessionMetrics.estimated_cost.toFixed(4) }}<span v-if="sessionMetrics.final_status"> · {{ sessionMetrics.final_status }}</span></span>
        </div>
      </div>

      <div v-if="sessionMetrics" class="admin-section">
        <div class="admin-stat-title">효율 계측</div>
        <div class="metric-grid">
          <div class="metric-cell"><span class="metric-num">{{ Math.round((sessionMetrics.cache_hit_ratio || 0) * 100) }}%</span><span class="metric-lbl">cache 적중</span></div>
          <div v-if="sessionMetrics.tool_raw_tokens" class="metric-cell"><span class="metric-num">{{ Math.round((1 - sessionMetrics.tool_visible_tokens / sessionMetrics.tool_raw_tokens) * 100) }}%</span><span class="metric-lbl">tool 출력 절감</span></div>
          <div class="metric-cell"><span class="metric-num">{{ (sessionMetrics.total_model_calls || 0).toLocaleString() }}</span><span class="metric-lbl">model 호출</span></div>
          <div class="metric-cell"><span class="metric-num">{{ (sessionMetrics.total_tool_calls || 0).toLocaleString() }}</span><span class="metric-lbl">tool 호출</span></div>
          <div class="metric-cell"><span class="metric-num">{{ sessionMetrics.pro_calls || 0 }}</span><span class="metric-lbl">Pro 호출</span></div>
          <div class="metric-cell"><span class="metric-num">{{ sessionMetrics.total_compactions || 0 }}</span><span class="metric-lbl">압축</span></div>
          <div class="metric-cell"><span class="metric-num">{{ sessionMetrics.total_retries || 0 }}</span><span class="metric-lbl">재시도</span></div>
        </div>
        <div v-if="sessionMetrics.selected_skills" class="admin-sub">skill: {{ sessionMetrics.selected_skills }}</div>
        <div v-for="(b, bi) in (sessionMetrics.bottlenecks || [])" :key="bi" class="metric-warn">⚠ {{ b }}</div>
      </div>

      <div v-if="ctxBreakdown && ctxBreakdown.areas" class="admin-section">
        <div class="admin-stat-title">Context 분해 (마지막 호출 · 추정)</div>
        <div class="admin-sub">약 {{ ctxBreakdown.total_est.toLocaleString() }} tok · 예산 대비 {{ ctxBreakdown.pct_est }}%</div>
        <div v-for="(tok, area) in ctxBreakdown.areas" :key="area" class="ctx-row">
          <span class="ctx-label">{{ CTX_LABELS[area] || area }}</span>
          <div class="ctx-bar"><div class="ctx-fill" :style="{ width: (ctxBreakdown.total_est ? Math.round(tok / ctxBreakdown.total_est * 100) : 0) + '%' }"></div></div>
          <span class="ctx-tok mono">{{ tok.toLocaleString() }}</span>
        </div>
      </div>

      <div v-if="toolUsage.length" class="admin-section">
        <div class="admin-stat-title">도구별 호출</div>
        <div v-for="t in toolUsage" :key="t.name" class="admin-row">
          <span>{{ t.name }}</span>
          <span class="mono">×{{ t.count.toLocaleString() }}</span>
        </div>
      </div>

      <div class="admin-section">
        <div class="admin-stat-title">에이전트별 사용량</div>
        <div v-for="a in sessionRoleBreakdown()" :key="a.role" class="admin-row">
          <span>{{ a.role }} <span class="run-count">×{{ a.count }}</span></span>
          <span class="mono">{{ formatTokens(a.total) }}</span>
        </div>
        <div v-if="!sessionRuns.length" class="admin-sub">기록 없음</div>
      </div>

      <div class="admin-section">
        <div class="admin-stat-title">모델별 사용량</div>
        <div v-for="m in sessionModelBreakdown()" :key="m.model" class="admin-row">
          <span>{{ m.model }} <span class="run-count">×{{ m.count }}</span></span>
          <span class="mono">{{ formatTokens(m.total) }}</span>
        </div>
        <div v-if="!sessionRuns.length" class="admin-sub">기록 없음</div>
      </div>

      <button v-if="sessionRuns.length" class="detail-link" @click="showRunHistory = true">
        실행 이력 {{ sessionRuns.length }}건 전체 보기 →
      </button>
    </div>
  </div>

  <div v-if="showRunHistory" class="kanban-overlay">
    <div class="kanban-head">
      <span class="kanban-title">{{ roomTitle }} · 실행 이력</span>
      <button @click="showRunHistory = false">닫기</button>
    </div>
    <div class="admin-body">
      <div v-if="!sessionRuns.length" class="admin-sub">기록 없음</div>
      <div v-for="(r, i) in sessionRuns" :key="i" class="run-item">
        <div class="run-head">
          <span class="run-role">{{ ROLE_LABELS[r.role] || r.role }}</span>
          <span class="run-model">{{ r.model }}</span>
        </div>
        <div class="run-meta">
          prompt {{ formatTokens(r.prompt_tokens) }} · completion {{ formatTokens(r.completion_tokens) }}<span v-if="r.thinking_enabled"> · thinking {{ r.reasoning_effort }}</span>
        </div>
        <div class="run-meta">
          cache {{ formatTokens(r.cache_hit_tokens) }}↔{{ formatTokens(r.cache_miss_tokens) }} · model {{ r.model_calls }} · tool {{ r.tool_calls }} · 재시도 {{ r.retries }} · 압축 {{ r.compactions }}<span v-if="r.elapsed_ms"> · {{ (r.elapsed_ms / 1000).toFixed(1) }}s</span>
        </div>
        <div v-if="r.selected_skills" class="run-meta">skill: {{ r.selected_skills }}</div>
        <div class="run-meta run-time">{{ r.created_at }}</div>
      </div>
    </div>
  </div>
</template>
