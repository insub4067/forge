// 메시지·phase 표현 헬퍼 — 상태(ref)를 참조하지 않는 순수 함수만 모은다.
// App.vue에서 분리해 단위 테스트가 가능하게 했다(message.test.js).

export const ROLE_LABELS = {
  triage: '분류',
  developer: '개발',
  chat: '응답',
  vision: '이미지 분석',
}

// 완료 semantic을 타임라인 터미널 노드로 — backend 실제 상태를 왜곡하지 않는다.
// completed_unverified를 ✓로 위장하지 않는다(검증 불완전은 !).
export const COMPLETION_NODES = {
  completed: { glyph: '✓', label: '완료', cls: 'done' },
  completed_unverified: { glyph: '!', label: '검증 불완전', cls: 'warn' },
  verification_failed: { glyph: '!', label: '검증 실패', cls: 'error' },
  context_blocked: { glyph: '!', label: '컨텍스트 한도 도달', cls: 'warn' },
  budget_exceeded: { glyph: '!', label: '예산 초과', cls: 'warn' },
  failed: { glyph: '!', label: '실패', cls: 'error' },
  cancelled: { glyph: '·', label: '중단됨', cls: 'muted' },
}

export function completionNode(status) {
  return COMPLETION_NODES[status] || null
}

export function phaseLabel(p) {
  if (p.role && ROLE_LABELS[p.role]) return ROLE_LABELS[p.role]
  const names = p.tools.map((t) => t.name)
  if (names.some((n) => n === 'write_file' || n === 'edit_file')) return '편집'
  if (names.includes('bash')) return '실행'
  if (names.some((n) => ['read_file', 'list_dir', 'grep'].includes(n))) return '탐색'
  return '응답'
}

// Tool Failure ≠ Activity Failure. 코딩 에이전트에게 read_file ENOENT·grep no-match 등은
// 탐색의 정상 과정이다. 도구 하나가 실패했다고 Activity 전체를 '!'로 만들지 않는다.
// Activity 실패(!)는 검증 실패/완료 터미널(completionNode)에서만 온다. 도구 실패는 통계로.
export function phaseStatus(p) {
  if (p.running) return 'running'
  return 'done'
}

export function phaseErrorCount(p) {
  return (p.tools || []).filter((t) => t.status === 'error').length
}

export function phaseGlyph(p) {
  const s = phaseStatus(p)
  return s === 'running' ? '●' : s === 'error' ? '!' : '✓'
}

export function phaseHasDetail(p) {
  return !!((p.tools && p.tools.length) || p.thinking)
}

export function runningTool(p) {
  return p.tools.find((t) => t.status === 'running')
}

export function firstSentence(t) {
  const m = t.match(/[.!?。](?=\s|$|[가-힣])/u)
  return m ? t.slice(0, m.index + 1).trim() : t.trim()
}

// 완료 phase는 결과형 시제로(미래형 "…하겠습니다" 제거).
export function phaseSummary(p) {
  const t = (p.text || '').trim()
  if (!t) return t
  const lead = phaseHasDetail(p) ? firstSentence(t) : t
  if (p.running) return lead
  const stripped = lead
    .replace(/(하겠습니다|하겠어요|하려고\s*합니다|해\s*보겠습니다|아?\s*보겠습니다|겠습니다)\s*[.。]?\s*$/u, '')
    .replace(/[.。\s]+$/u, '')
    .trim()
  return stripped || lead   // 통째로 비면(예: 문장 전체가 종결어미) lead 유지
}

// 도구·추론이 있거나, agent 작업 role(chat 아님)이면 Activity. 후자를 포함해야 developer/
// planner 등 phase가 시작되자마자(첫 도구 전에도) 라이브 타임라인에 '● 실행 중'으로 뜬다.
// 순수 대화(role 'chat' 또는 '')는 도구가 없으면 상태 기호 없이 본문만.
export function hasActivity(m) {
  return (m.phases || []).some(
    (p) => (p.tools && p.tools.length) || p.thinking || (p.role && p.role !== 'chat'))
}

export function assistantText(m) {
  const parts = (m.phases || []).map((p) => p.text).filter(Boolean)
  if (m.doneMessage) parts.push(m.doneMessage)
  return parts.join('\n\n').trim()
}

export function hasAssistantText(m) {
  return assistantText(m).length > 0
}

// 완료 보고인가 — format_completion_summary의 고정 헤더로 판별(backend와 동기화 필수).
export function isCompletionReport(text) {
  const t = (text || '').trim()
  return t.startsWith('완료했습니다.') || t.startsWith('작업은 완료했습니다. 다만')
}

export function shortModel(m) {
  if (!m) return ''
  if (m.includes('pro')) return 'Pro'
  if (m.includes('vision')) return 'Vision'
  if (m.includes('flash')) return 'Flash'
  return m.split('/').pop()
}

export function summarizeArgs(args) {
  if (!args || typeof args !== 'object') return ''
  if (typeof args.command === 'string') return args.command.split('\n')[0].slice(0, 80)
  if (args.path) return String(args.path)
  if (args.pattern) return String(args.pattern)
  try {
    const s = JSON.stringify(args)
    return s.length > 80 ? s.slice(0, 80) + '…' : s
  } catch {
    return ''
  }
}

export function approvalBody(args) {
  if (!args || typeof args !== 'object') return ''
  if (typeof args.command === 'string') return args.command
  if (typeof args.content === 'string') return args.content.slice(0, 2000)
  if (typeof args.new_string === 'string') {
    return '- ' + String(args.old_string || '').slice(0, 600) + '\n+ ' + args.new_string.slice(0, 600)
  }
  return ''
}

export function formatTokens(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n || 0)
}

export function shortPath(p) {
  if (!p) return ''
  const parts = p.split('/').filter(Boolean)
  if (parts.length <= 2) return p
  return parts.slice(-2).join('/')
}
