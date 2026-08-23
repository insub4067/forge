<script setup>
// Git 패널 — 브랜치/변경/히스토리/원격 동기화를 표시한다.
// App.vue의 git 관련 상태·함수·마크업을 이 컴포넌트로 이관.
import { ref, onMounted } from 'vue'

const props = defineProps({
  roomId: { type: String, default: '' },
  workspacePath: { type: String, default: '' },
})
const emit = defineEmits(['close'])

const gitCurrent = ref('')
const gitBranches = ref([])
const gitStatus = ref('')
const gitError = ref('')
const gitLoading = ref(false)
const gitTab = ref('changes') // 'changes' | 'history' | 'branches'
const gitFiles = ref([])
const gitLog = ref([])
const gitLogHasMore = ref(false)
const gitLogLoadingMore = ref(false)
const gitDetail = ref(null) // { title, sub, diff, loading }
const gitRemote = ref({ ahead: 0, behind: 0, has_upstream: false, loading: false }) // 원격 대비 push/pull 수
const gitSyncing = ref('') // '' | 'push' | 'pull'

function repoName(p) {
  if (!p) return 'FORGE'
  const parts = p.split('/').filter(Boolean)
  return parts[parts.length - 1] || 'FORGE'
}

async function loadGit() {
  const id = props.roomId
  if (!id) {
    gitError.value = '세션을 먼저 선택하세요.'
    return
  }
  gitError.value = ''
  gitDetail.value = null
  gitLoading.value = true
  const get = async (path) => {
    try {
      const r = await fetch(`/api/rooms/${id}/${path}`)
      if (!r.ok) throw new Error('HTTP ' + r.status)
      return await r.json()
    } catch (e) {
      gitError.value = 'Git 정보를 불러오지 못했습니다: ' + (e.message || e)
      return null
    }
  }
  // 각 요청을 독립 처리 — 하나 실패해도 나머지는 표시한다.
  const [b, s, l] = await Promise.all([get('git/branches'), get('git/status'), get('git/log')])
  if (b) {
    gitCurrent.value = b.current || ''
    gitBranches.value = b.branches || []
  }
  if (s) {
    gitStatus.value = s.output || ''
    gitFiles.value = parseStatus(s.output || '')
  }
  if (l) {
    gitLog.value = l.commits || []
    gitLogHasMore.value = !!l.has_more
  }
  gitLoading.value = false
  loadRemote() // 원격 대비 ahead/behind — 네트워크 fetch라 비동기로 뒤따르게(패널은 즉시 표시)
}

// 원격(origin) 대비 push/pull 필요 커밋 수. git fetch 후 rev-list 카운트.
async function loadRemote() {
  const id = props.roomId
  if (!id) return
  gitRemote.value = { ...gitRemote.value, loading: true }
  try {
    const r = await fetch(`/api/rooms/${id}/git/remote`)
    gitRemote.value = r.ok ? { ...(await r.json()), loading: false } : { ...gitRemote.value, loading: false }
  } catch {
    gitRemote.value = { ...gitRemote.value, loading: false }
  }
}

async function gitPush() {
  const id = props.roomId
  if (!id || gitSyncing.value) return
  if (!confirm('원격(origin)으로 push할까요?')) return
  gitSyncing.value = 'push'
  try {
    const r = await fetch(`/api/rooms/${id}/git/push`, { method: 'POST' })
    const d = await r.json().catch(() => ({}))
    if (d.output && /rejected|error|오류|fatal/i.test(d.output)) gitError.value = 'Push 실패: ' + d.output
  } catch (e) {
    gitError.value = 'Push 실패: ' + (e.message || e)
  } finally {
    gitSyncing.value = ''
    await loadRemote()
  }
}

async function gitPull() {
  const id = props.roomId
  if (!id || gitSyncing.value) return
  gitSyncing.value = 'pull'
  try {
    const r = await fetch(`/api/rooms/${id}/git/pull`, { method: 'POST' })
    const d = await r.json().catch(() => ({}))
    if (d.output && /conflict|error|오류|fatal|abort/i.test(d.output)) gitError.value = 'Pull 실패: ' + d.output
  } catch (e) {
    gitError.value = 'Pull 실패: ' + (e.message || e)
  } finally {
    gitSyncing.value = ''
    await loadRemote()
    await loadGit()
  }
}

// git 히스토리 무한 스크롤 — 다음 페이지를 이어붙인다.
async function loadMoreGitLog() {
  const id = props.roomId
  if (!id || gitLogLoadingMore.value || !gitLogHasMore.value) return
  gitLogLoadingMore.value = true
  try {
    const r = await fetch(`/api/rooms/${id}/git/log?skip=${gitLog.value.length}&limit=50`)
    if (r.ok) {
      const d = await r.json()
      gitLog.value = gitLog.value.concat(d.commits || [])
      gitLogHasMore.value = !!d.has_more
    }
  } catch {
  } finally {
    gitLogLoadingMore.value = false
  }
}

function onGitScroll(e) {
  if (gitTab.value !== 'history') return
  const el = e.target
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 120) loadMoreGitLog()
}

function parseStatus(raw) {
  return raw
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => {
      // git status --short는 "XY path"(2칸 코드+공백). 백엔드 _git의 strip()이
      // 첫 줄 앞 공백을 먹어 정렬이 밀리므로, 구분 공백이 없으면 복원한다.
      if (line[2] !== ' ') line = ' ' + line
      const code = line.slice(0, 2)
      let path = line.slice(3)
      if (path.includes(' -> ')) path = path.split(' -> ')[1] // rename
      path = path.replace(/^"|"$/g, '')
      const c = code.replace(/\s/g, '')
      let badge = 'M', cls = 'st-mod'
      if (code.includes('?')) { badge = 'U'; cls = 'st-new' }
      else if (c.includes('A')) { badge = 'A'; cls = 'st-new' }
      else if (c.includes('D')) { badge = 'D'; cls = 'st-del' }
      else if (c.includes('R')) { badge = 'R'; cls = 'st-ren' }
      else if (c.includes('U')) { badge = '!'; cls = 'st-del' }
      return { badge, cls, path }
    })
}

async function openFileDiff(f) {
  const id = props.roomId
  gitDetail.value = { title: f.path, sub: '변경 사항', diff: '', loading: true }
  try {
    const r = await fetch(`/api/rooms/${id}/git/file-diff?path=${encodeURIComponent(f.path)}`)
    const d = await r.json()
    gitDetail.value = { title: f.path, sub: '변경 사항', diff: d.diff || '', loading: false }
  } catch {
    gitDetail.value = { title: f.path, sub: '변경 사항', diff: '', loading: false }
  }
}

async function openCommit(c) {
  const id = props.roomId
  const sub = `${c.author} · ${c.date} · ${c.hash}`
  gitDetail.value = { title: c.subject, sub, diff: '', loading: true }
  try {
    const r = await fetch(`/api/rooms/${id}/git/commit?hash=${encodeURIComponent(c.hash)}`)
    const d = await r.json()
    gitDetail.value = {
      title: d.subject || c.subject,
      sub: `${d.author || c.author} · ${d.date || c.date} · ${d.hash || c.hash}`,
      diff: d.diff || '',
      loading: false,
    }
  } catch {
    gitDetail.value = { title: c.subject, sub, diff: '', loading: false }
  }
}

async function checkoutBranch(branch) {
  const id = props.roomId
  if (!id) return
  try {
    await fetch(`/api/rooms/${id}/git/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ branch }),
    })
    await loadGit()
  } catch {}
}

function diffLines(diff) {
  return diff.split('\n')
}

function diffClass(line) {
  if (line.startsWith('+') && !line.startsWith('+++')) return 'add'
  if (line.startsWith('-') && !line.startsWith('---')) return 'del'
  if (line.startsWith('@@')) return 'hunk'
  return ''
}

onMounted(loadGit)
</script>

<template>
  <div class="gh-overlay">
    <div class="gh-head">
      <div class="gh-repo">
        <div class="gh-repo-name">{{ repoName(workspacePath) }}</div>
        <div class="gh-branch">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M9.5 3.25a2.25 2.25 0 1 1 3 2.122V6A2.5 2.5 0 0 1 10 8.5H6a1 1 0 0 0-1 1v1.128a2.251 2.251 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.5 0v1.836A2.492 2.492 0 0 1 6 7h4a1 1 0 0 0 1-1v-.628A2.25 2.25 0 0 1 9.5 3.25Zm-6 0a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Zm8.25-.75a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5ZM4.25 12a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Z"/></svg>
          <span>{{ gitCurrent || '—' }}</span>
        </div>
      </div>
      <div class="gh-head-actions">
        <button class="gh-icon-btn" :disabled="gitLoading" @click="loadGit" aria-label="새로고침">
          <svg :class="{ spin: gitLoading }" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6M3 12a9 9 0 0 1 15-6.7L21 8M3 22v-6h6M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
        </button>
        <button class="gh-close" @click="emit('close')">닫기</button>
      </div>
    </div>

    <div v-if="!gitDetail" class="gh-sync">
      <div class="gh-sync-counts">
        <span class="gh-sync-badge up" :class="{ zero: !gitRemote.ahead }" title="push 필요">↑ {{ gitRemote.ahead }}</span>
        <span class="gh-sync-badge down" :class="{ zero: !gitRemote.behind }" title="pull 필요">↓ {{ gitRemote.behind }}</span>
        <span v-if="gitRemote.loading" class="gh-sync-note">원격 확인 중…</span>
        <span v-else-if="!gitRemote.has_upstream" class="gh-sync-note">원격 추적 없음</span>
      </div>
      <div class="gh-sync-actions">
        <button class="gh-sync-btn" :disabled="!gitRemote.behind || !!gitSyncing" @click="gitPull">
          {{ gitSyncing === 'pull' ? 'Pull 중…' : 'Pull' }}
        </button>
        <button class="gh-sync-btn primary" :disabled="!gitRemote.ahead || !!gitSyncing" @click="gitPush">
          {{ gitSyncing === 'push' ? 'Push 중…' : 'Push' }}
        </button>
      </div>
    </div>

    <div v-if="gitDetail" class="gh-detail">
      <div class="gh-detail-head">
        <button class="gh-back" @click="gitDetail = null">‹ 뒤로</button>
      </div>
      <div class="gh-detail-title">{{ gitDetail.title }}</div>
      <div v-if="gitDetail.sub" class="gh-detail-sub">{{ gitDetail.sub }}</div>
      <div v-if="gitDetail.loading" class="gh-empty">불러오는 중…</div>
      <div v-else-if="gitDetail.diff" class="diff gh-diff">
        <div v-for="(line, li) in diffLines(gitDetail.diff)" :key="li" :class="diffClass(line)">{{ line || ' ' }}</div>
      </div>
      <div v-else class="gh-empty">표시할 변경 내용이 없습니다.</div>
    </div>

    <template v-else>
      <div class="gh-tabs">
        <button :class="{ active: gitTab === 'changes' }" @click="gitTab = 'changes'">
          변경<span v-if="gitFiles.length" class="gh-badge">{{ gitFiles.length }}</span>
        </button>
        <button :class="{ active: gitTab === 'history' }" @click="gitTab = 'history'">히스토리</button>
        <button :class="{ active: gitTab === 'branches' }" @click="gitTab = 'branches'">브랜치</button>
      </div>

      <div v-if="gitError" class="git-error">{{ gitError }}</div>

      <div class="gh-content" @scroll="onGitScroll">
        <template v-if="gitTab === 'changes'">
          <div v-if="!gitLoading && !gitFiles.length" class="gh-empty">변경 사항이 없습니다.</div>
          <div v-for="f in gitFiles" :key="f.path" class="gh-file" @click="openFileDiff(f)">
            <span class="gh-status" :class="f.cls">{{ f.badge }}</span>
            <span class="gh-file-path">{{ f.path }}</span>
            <svg class="gh-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>
          </div>
        </template>

        <template v-else-if="gitTab === 'history'">
          <div v-if="!gitLoading && !gitLog.length" class="gh-empty">커밋이 없습니다.</div>
          <div v-for="c in gitLog" :key="c.hash" class="gh-commit" @click="openCommit(c)">
            <div class="gh-avatar">{{ (c.author || '?').slice(0, 1).toUpperCase() }}</div>
            <div class="gh-commit-body">
              <div class="gh-commit-subject">{{ c.subject }}</div>
              <div class="gh-commit-meta">{{ c.author }} · {{ c.date }} · {{ c.hash }}</div>
            </div>
          </div>
          <div v-if="gitLogLoadingMore" class="gh-empty">더 불러오는 중…</div>
          <div v-else-if="gitLog.length && !gitLogHasMore" class="gh-empty">마지막 커밋입니다.</div>
        </template>

        <template v-else>
          <div v-if="!gitBranches.length" class="gh-empty">브랜치가 없습니다.</div>
          <div
            v-for="b in gitBranches"
            :key="b"
            class="gh-branch-row"
            :class="{ current: b === gitCurrent }"
            @click="checkoutBranch(b)"
          >
            <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M9.5 3.25a2.25 2.25 0 1 1 3 2.122V6A2.5 2.5 0 0 1 10 8.5H6a1 1 0 0 0-1 1v1.128a2.251 2.251 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.5 0v1.836A2.492 2.492 0 0 1 6 7h4a1 1 0 0 0 1-1v-.628A2.25 2.25 0 0 1 9.5 3.25Zm-6 0a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Zm8.25-.75a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5ZM4.25 12a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Z"/></svg>
            <span class="gh-branch-name">{{ b }}</span>
            <span v-if="b === gitCurrent" class="gh-current-tag">현재</span>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>
