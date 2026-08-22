# Home Camera Monitor 도입 제안

> 상태: Proposal / Optional Module
> 목표: FORGE가 실행되는 개인 장비에 연결된 카메라 또는 사용자가 소유·관리하는 네트워크 카메라를 모바일 PWA에서 안전하게 확인하고, 향후 Condition Job과 연동할 수 있는 선택형 모듈을 정의한다.

## 1. 범위

이 기능은 FORGE의 핵심 Coding Harness 기능이 아니다.

따라서 AgentRuntime에 직접 결합하지 않고 **optional remote-device module**로 분리한다.

목표 사용 사례:

- 외출 중 집/작업실 상태 확인
- Mac에 연결된 USB camera 확인
- 사용자가 소유한 RTSP/IP camera 확인
- 필요할 때만 live stream 시작
- 향후 motion/event 발생 시 Condition Job 연동

타인이나 사용자의 권한이 없는 장소/카메라를 감시하는 용도로 설계하지 않는다.

## 2. 구조

로컬 카메라:

```text
USB / Built-in Camera
        ↓
AVFoundation
        ↓
WebRTC
        ↓
FORGE PWA
```

네트워크 카메라:

```text
Owned IP Camera
      ↓
RTSP / supported source
      ↓
FORGE Camera Gateway
      ↓
WebRTC
      ↓
PWA
```

FastAPI는 camera metadata, session authorization, signaling을 담당한다.

## 3. 핵심 원칙

- 기본 비활성화
- 명시적으로 등록된 camera만 사용
- camera credential을 frontend에 노출하지 않음
- public stream URL 생성 금지
- recording 기본 비활성화
- 영상/사진을 Agent에게 자동 전달하지 않음
- camera 기능 장애가 AgentRuntime에 영향을 주지 않음

## 4. Camera Registry

예시 모델:

```text
Camera
- id
- name
- type
- source configuration
- enabled
- created_at
```

민감한 RTSP credential은 DB 평문 저장을 피하고 secure secret storage를 사용한다.

Frontend에는 실제 source URL/credential을 반환하지 않는다.

## 5. Live Streaming

모바일에서의 실시간 확인은 WebRTC를 우선 검토한다.

```text
Camera Source
→ Decode/Transform if needed
→ WebRTC
→ Browser
```

IP camera가 H.264 등을 제공하면 불필요한 transcoding을 최소화하는 방향을 검토한다.

## 6. UI

별도 optional 메뉴로 둔다.

```text
Remote Devices

Camera
├─ 거실       ● Online
├─ 현관       ● Online
└─ 작업실     ○ Offline
```

카메라 선택:

```text
거실
● LIVE

┌───────────────────┐
│                   │
│    Camera Feed    │
│                   │
└───────────────────┘

[Stop Stream]
```

## 7. Motion / Event Detection

초기 v1에는 포함하지 않아도 된다.

향후 다음 구조로 Condition Job과 연결할 수 있다.

```text
Camera
  ↓
Motion/Event Detector
  ↓
Event
  ↓
Condition Job
  ↓
Notification
```

중요한 원칙은 **상시 LLM Vision 분석을 하지 않는 것**이다.

움직임 감지는 가능한 한 저비용 local CV/device event로 처리한다.

필요한 event가 발생했을 때만 snapshot을 Vision model로 보내는 방식을 검토한다.

이는 비용과 개인정보 노출을 모두 줄인다.

## 8. Vision 연동

향후 예:

```text
Motion detected
→ snapshot
→ Vision
→ "사람 감지"
→ notification
```

하지만 자동 Vision은 opt-in이어야 한다.

영상 전체를 모델 provider로 전송하지 않는다.

단일 frame 또는 짧게 제한된 event data만 처리한다.

사용자에게 외부 모델 API로 이미지가 전송될 수 있음을 명확하게 알린다.

## 9. Recording

초기에는 녹화를 지원하지 않는다.

Live View와 Recording은 개인정보/저장공간/보안 요구사항이 크게 다르기 때문이다.

향후 recording이 필요하면 별도 proposal로 다룬다.

## 10. 보안

Camera는 화면 Preview보다 더 민감한 기능으로 취급한다.

필수 원칙:

- authenticated session
- camera별 authorization
- unguessable session token
- credential server-side 보관
- TLS
- public camera endpoint 금지
- stream URL 장기 재사용 금지
- access audit metadata
- stream 종료 시 session 폐기

Remote FORGE는 Cloudflare Zero Trust/Access, VPN, Tailscale 등 신뢰 가능한 접근제어 뒤에서 운영하는 것을 권장한다.

Tunnel 자체는 authorization이 아니다.

## 11. SSRF / Network Camera

RTSP/IP camera source를 등록할 수 있게 되면 SSRF/internal-network 접근 문제가 생긴다.

일반 `web_fetch` 정책과는 별도로 **사용자가 명시적으로 등록한 camera endpoint만** camera gateway가 접근하도록 한다.

Agent가 임의 URL을 camera source로 추가할 수 없게 한다.

Camera 등록/credential 변경은 사용자 승인 작업이다.

## 12. Privacy

다음 원칙을 강제한다.

- 사용자가 소유하거나 접근 권한을 가진 camera만 등록
- camera active 상태 명확히 표시
- 영상 기본 저장 안 함
- thumbnail 장기 저장 안 함
- telemetry에 frame/content 저장 안 함
- Agent memory에 영상 자동 저장 안 함

카메라가 켜져 있는지 알 수 없는 은밀한 감시 기능을 목표로 하지 않는다.

## 13. Runtime 격리

Camera streaming process는 AgentRuntime과 분리한다.

```text
FORGE Control Plane
├─ Agent Worker
├─ Terminal Manager
├─ Screen Preview Service
└─ Camera Gateway (optional)
```

Camera codec/stream 장애가 Coding Agent 작업을 중단시키면 안 된다.

가능하면 별도 process/service boundary를 사용한다.

## 14. Resource Policy

- viewer가 없으면 stream 중단
- 최대 동시 stream 제한
- bitrate/FPS 제한
- transcoding 최소화
- offline camera timeout
- reconnect backoff

홈 모니터 때문에 FORGE Agent의 CPU/GPU resource가 고갈되지 않게 한다.

## 15. 단계

### C0 — USB Camera PoC
AVFoundation → local WebRTC viewer.

### C1 — Authenticated PWA Live View
signaling, authorization, mobile UI.

### C2 — Camera Registry
여러 camera 등록/상태 관리.

### C3 — RTSP Gateway
사용자가 소유한 IP camera 지원.

### C4 — Condition Job Integration
motion/device event → notification.

### C5 — Optional Vision Event Analysis
명시적 opt-in snapshot analysis.

## 16. 하지 않을 것

초기에는 다음을 하지 않는다.

- 몰래 camera 활성화
- 권한 없는 camera 탐색
- 인터넷상의 camera scan
- 얼굴 식별 시스템
- 상시 cloud Vision 분석
- 기본 24시간 recording
- 영상 광고/외부 분석 제공
- Agent가 임의 camera credential을 획득/변경

## 17. 완료 기준

1. 기능이 기본적으로 꺼져 있다.
2. 사용자가 직접 등록/허용한 camera만 접근 가능하다.
3. iPhone PWA에서 live stream을 볼 수 있다.
4. camera credential이 browser에 노출되지 않는다.
5. 영상이 기본적으로 저장되지 않는다.
6. AgentRuntime과 streaming runtime이 격리된다.
7. unauthorized user가 stream을 열 수 없다.
8. viewer가 없으면 불필요한 streaming resource가 정리된다.
9. 향후 Condition Job과 event interface로 연결할 수 있다.

## 결론

Home Camera Monitor는 FORGE의 핵심 Coding Harness와 분리된 **선택형 Remote Device 기능**으로만 도입한다.

핵심 방향은:

> **Explicit Camera Registration → Authenticated Live View → Optional Local Event Detection → Condition Job**

이다.

상시 AI 감시 시스템으로 만들지 않고, 필요할 때 안전하게 집/작업실 상태를 확인하는 개인 self-hosted 기능으로 제한한다.
