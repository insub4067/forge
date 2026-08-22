# Live Screen Preview 도입 제안

> 상태: Proposal
> 목표: FORGE PWA에서 Mac의 전체 화면 또는 특정 앱/윈도우/Simulator를 저지연으로 확인할 수 있는 View-only 실시간 화면 기능을 제공한다.

## 1. 목적

FORGE는 모바일에서 Agent 작업 상태와 Terminal을 확인할 수 있는 방향으로 발전하고 있다. 하지만 UI 작업, Simulator 실행, Browser 결과처럼 실제 화면 상태가 중요한 작업은 텍스트 로그만으로 충분하지 않다.

Live Screen Preview는 원격 데스크톱을 만드는 것이 아니라 **Agent가 작업 중인 시각적 결과를 사용자가 원격에서 검증하는 기능**을 목표로 한다.

## 2. 목표 구조

```text
macOS
  ↓
ScreenCaptureKit
  ↓
Video Encode
  ↓
WebRTC
  ↓
FORGE PWA
  ↓
Live Preview
```

FastAPI는 signaling/session authorization을 담당하고 영상 데이터 자체는 가능하면 WebRTC peer connection으로 전달한다.

## 3. 초기 범위

v1은 View-only로 제한한다.

지원 후보:

- 전체 Display
- 특정 Window
- 특정 Application
- iOS Simulator window
- stream start/stop
- 해상도/FPS 제한
- 모바일 전체화면
- 연결 상태 표시

초기에는 원격 mouse/keyboard 입력을 지원하지 않는다.

## 4. macOS Capture

macOS에서는 ScreenCaptureKit 사용을 우선한다.

사용자는 macOS Screen Recording 권한을 명시적으로 승인해야 한다.

권한이 없을 경우 FORGE가 우회하려 하지 않고 명확한 설정 안내를 제공한다.

## 5. WebRTC

Live Preview는 저지연이 중요하므로 HLS보다 WebRTC를 우선 검토한다.

```text
Capture → Encode → WebRTC → Browser Video
```

FastAPI는 offer/answer/ICE signaling과 authorization을 담당할 수 있다.

외부 접속 환경에서는 NAT/네트워크 조건에 따라 STUN/TURN 필요성을 PoC에서 검증한다.

## 6. UI

기존 FORGE에 독립된 Preview 화면을 둔다.

```text
[Agent] [Terminal] [Preview]

Preview
● LIVE — iOS Simulator

┌─────────────────────┐
│                     │
│   Simulator Screen  │
│                     │
└─────────────────────┘
```

모바일에서는 landscape/fullscreen을 지원한다.

## 7. Agent와의 관계

Preview 영상 전체를 LLM에 자동 전달하지 않는다.

사람이 보는 실시간 스트림과 Agent Vision 입력은 다른 경계다.

향후 사용자가 명시적으로 `현재 화면을 Agent에게 보여주기`를 실행하면 단일 frame/screenshot을 기존 Vision pipeline으로 전달하는 기능을 별도로 검토할 수 있다.

## 8. 보안

화면에는 credential, 개인정보, 내부 시스템 정보가 노출될 수 있다.

따라서:

- authenticated session 필수
- stream별 authorization
- 임의 public stream URL 금지
- recording 기본 비활성화
- stream 종료 시 resource 즉시 해제
- 화면 frame을 DB/log에 기본 저장하지 않음
- remote deployment는 Zero Trust/VPN 등 별도 접근통제 권장

Cloudflare Tunnel 자체를 authorization으로 간주하지 않는다.

## 9. Privacy Indicator

화면 공유 중이라는 사실이 Mac과 PWA 양쪽에서 명확해야 한다.

예:

```text
● Screen sharing active
Source: iOS Simulator
[Stop]
```

백그라운드에서 몰래 capture하는 기능으로 만들지 않는다.

## 10. Resource Policy

Preview 때문에 Agent 작업 성능이 크게 저하되면 안 된다.

- FPS 제한
- 최대 해상도 제한
- adaptive bitrate 검토
- viewer가 없으면 capture 중단
- 여러 viewer 제한

실제 기본값은 PoC 측정 후 결정한다.

## 11. 단계

### S0 — Local PoC
ScreenCaptureKit → 단일 browser preview.

### S1 — WebRTC
저지연 streaming + signaling.

### S2 — Source Selection
Display/Window/Application/Simulator 선택.

### S3 — Mobile UX
fullscreen, landscape, reconnect.

### S4 — Harness Integration
Agent 작업 화면 연결 및 명시적 screenshot-to-Vision.

## 12. 하지 않을 것

초기에는 다음을 하지 않는다.

- 원격 mouse/keyboard control
- 화면 녹화 서비스
- 무제한 다중 viewer
- 화면 전체를 지속적으로 LLM Vision에 전달
- Jump Desktop/VNC 완전 대체

## 13. 완료 기준

1. Mac에서 명시적으로 화면 공유를 시작할 수 있다.
2. iPhone PWA에서 낮은 지연으로 화면을 확인할 수 있다.
3. 특정 Window/Simulator만 선택 가능하다.
4. 권한 없는 사용자가 stream에 접근할 수 없다.
5. 영상 frame이 기본적으로 영구 저장되지 않는다.
6. viewer가 사라지면 불필요한 capture resource를 정리한다.
7. Agent inference 성능에 과도한 영향을 주지 않는다.

## 결론

Live Screen Preview는 FORGE를 원격 데스크톱으로 바꾸기 위한 기능이 아니다.

**Agent가 만든 실제 UI 결과를 모바일에서 즉시 확인할 수 있는 Human-in-the-loop 관찰 계층**으로 구현한다.

v1은 `ScreenCaptureKit → WebRTC → PWA, View-only`에 집중한다.
