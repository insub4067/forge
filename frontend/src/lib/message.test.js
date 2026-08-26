import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  phaseLabel, phaseStatus, phaseGlyph, phaseErrorCount, phaseHasDetail, phaseSummary,
  firstSentence, hasActivity, assistantText, hasAssistantText, isCompletionReport,
  completionNode, shortModel, summarizeArgs, approvalBody, formatTokens, shortPath, runningTool,
} from './message.js'

const phase = (o = {}) => ({ role: '', text: '', thinking: '', tools: [], running: false, ...o })

test('phaseLabel: role 우선, 없으면 도구로 추론', () => {
  assert.equal(phaseLabel(phase({ role: 'developer' })), '개발')
  assert.equal(phaseLabel(phase({ tools: [{ name: 'edit_file' }] })), '편집')
  assert.equal(phaseLabel(phase({ tools: [{ name: 'bash' }] })), '실행')
  assert.equal(phaseLabel(phase({ tools: [{ name: 'grep' }] })), '탐색')
  assert.equal(phaseLabel(phase()), '응답')
  // 편집이 실행보다 우선 — 편집+bash면 '편집'
  assert.equal(phaseLabel(phase({ tools: [{ name: 'bash' }, { name: 'write_file' }] })), '편집')
})

test('도구 실패는 phase를 error로 만들지 않는다 (Tool Failure ≠ Activity Failure)', () => {
  const p = phase({ tools: [{ name: 'read_file', status: 'error' }] })
  assert.equal(phaseStatus(p), 'done')
  assert.equal(phaseGlyph(p), '✓')
  assert.equal(phaseErrorCount(p), 1)   // 실패는 통계로만 센다
  assert.equal(phaseStatus(phase({ running: true })), 'running')
  assert.equal(phaseGlyph(phase({ running: true })), '●')
})

test('phaseHasDetail / runningTool', () => {
  assert.equal(phaseHasDetail(phase()), false)
  assert.equal(phaseHasDetail(phase({ thinking: 'x' })), true)
  assert.equal(phaseHasDetail(phase({ tools: [{ name: 'bash' }] })), true)
  const running = { name: 'bash', status: 'running' }
  assert.equal(runningTool(phase({ tools: [{ name: 'grep', status: 'done' }, running] })), running)
  assert.equal(runningTool(phase({ tools: [] })), undefined)
})

test('firstSentence: 한글 뒤 마침표도 문장 끝으로 본다', () => {
  assert.equal(firstSentence('먼저 확인합니다. 그다음 고칩니다.'), '먼저 확인합니다.')
  assert.equal(firstSentence('문장부호 없음'), '문장부호 없음')
})

test('phaseSummary: 완료 phase는 미래형 종결어미를 벗긴다', () => {
  const done = phase({ text: '구조를 확인하겠습니다.', tools: [{ name: 'grep' }] })
  assert.equal(phaseSummary(done), '구조를 확인')
  // 실행 중이면 그대로 둔다(진행 표현 유지)
  assert.equal(phaseSummary({ ...done, running: true }), '구조를 확인하겠습니다.')
  // 통째로 비면 lead 유지 — 빈 문자열로 만들지 않는다
  assert.equal(phaseSummary(phase({ text: '하겠습니다' })), '하겠습니다')
  assert.equal(phaseSummary(phase({ text: '' })), '')
})

test('hasActivity: 도구·추론·작업role이면 Activity, 순수 대화는 아니다', () => {
  assert.equal(hasActivity({ phases: [phase({ role: 'chat' })] }), false)
  assert.equal(hasActivity({ phases: [phase({ role: 'developer' })] }), true)
  assert.equal(hasActivity({ phases: [phase({ thinking: 'x' })] }), true)
  assert.equal(hasActivity({ phases: [] }), false)
  assert.equal(hasActivity({}), false)
})

test('assistantText: phase 텍스트 + doneMessage를 합친다', () => {
  const m = { phases: [phase({ text: 'a' }), phase({ text: '' }), phase({ text: 'b' })], doneMessage: 'c' }
  assert.equal(assistantText(m), 'a\n\nb\n\nc')
  assert.equal(hasAssistantText(m), true)
  assert.equal(hasAssistantText({ phases: [] }), false)
})

test('isCompletionReport: 완료 보고 헤더만 인식 (backend 문구와 동기화)', () => {
  assert.equal(isCompletionReport('완료했습니다.\n✓ 테스트 통과'), true)
  assert.equal(isCompletionReport('작업은 완료했습니다. 다만 일부 항목은 검증하지 못했습니다.'), true)
  // 일반 답변을 완료 보고로 오인하지 않는다 — 오인하면 실제 답변이 본문에서 사라진다
  assert.equal(isCompletionReport('파악 완료했습니다. 요약드립니다.'), false)
  assert.equal(isCompletionReport(''), false)
  assert.equal(isCompletionReport(null), false)
})

test('completionNode: completed_unverified를 ✓로 위장하지 않는다', () => {
  assert.equal(completionNode('completed').glyph, '✓')
  assert.equal(completionNode('completed_unverified').glyph, '!')
  assert.equal(completionNode('verification_failed').cls, 'error')
  assert.equal(completionNode('없는상태'), null)
})

test('shortModel / formatTokens / shortPath', () => {
  assert.equal(shortModel('deepseek-v4-pro'), 'Pro')
  assert.equal(shortModel('deepseek-v4-flash'), 'Flash')
  assert.equal(shortModel('x/custom-model'), 'custom-model')
  assert.equal(shortModel(''), '')
  assert.equal(formatTokens(1500), '1.5K')
  assert.equal(formatTokens(2000000), '2.0M')
  assert.equal(formatTokens(0), '0')
  assert.equal(shortPath('/Users/me/Desktop/forge'), 'Desktop/forge')
  assert.equal(shortPath('/tmp'), '/tmp')
  assert.equal(shortPath(''), '')
})

test('summarizeArgs: command 첫 줄 → path → pattern → JSON', () => {
  assert.equal(summarizeArgs({ command: 'ls -la\ncd /tmp' }), 'ls -la')
  assert.equal(summarizeArgs({ path: '/a/b.py' }), '/a/b.py')
  assert.equal(summarizeArgs({ pattern: 'foo' }), 'foo')
  assert.equal(summarizeArgs({ x: 1 }), '{"x":1}')
  assert.equal(summarizeArgs(null), '')
  assert.ok(summarizeArgs({ command: 'x'.repeat(200) }).length <= 80)
})

test('approvalBody: 승인 카드에 보여줄 본문', () => {
  assert.equal(approvalBody({ command: 'rm -rf x' }), 'rm -rf x')
  assert.equal(approvalBody({ content: 'abc' }), 'abc')
  assert.equal(approvalBody({ old_string: 'a', new_string: 'b' }), '- a\n+ b')
  assert.equal(approvalBody(null), '')
})
