# 원격 배포 보안

## 왜 이 문서

FORGE는 개인 Mac에서 도는 에이전트 코딩 런타임이다. host 모드에서는 bash가 컨테이너 격리 없이 호스트에서 직접 돌고, 터미널 셸·화면 캡처·입력 주입까지 노출된다. 이건 사실상 맥 전체를 다루는 권한이다. 로컬에서 혼자 쓸 때는 문제가 안 되지만, 이 런타임을 원격에서 조종할 수 있게 여는 순간 인증과 격리를 반드시 켜야 한다.

문제는 기본값이 전부 fail-open이라는 점이다. 아무것도 설정하지 않으면 인증은 무동작이고(`auth_token=""`, `require_auth=False`), CORS는 `*`로 열리며, host 모드 쓰기 방벽은 macOS가 아니면 그냥 통과한다. 편의를 위한 로컬 개발 기본값이 그대로 외부에 노출되면 무인증 원격 셸이 된다. 아래 체크리스트는 노출 전에 그 기본값을 닫는 절차다.

## 원격 배포 체크리스트

외부에서 접근 가능한 곳에 FORGE를 올리기 전에 전부 확인한다.

- **`FORGE_AUTH_TOKEN` 설정.** 미설정이면 토큰 미들웨어는 무동작이라 `/api/*`·WebSocket·`/uploads`가 인증 없이 열린다. 충분히 긴 랜덤 토큰을 넣는다. 설정하면 모든 요청이 `X-Forge-Token` 헤더·`forge_token` 쿠키·`?token=` 중 하나로 그 값을 요구한다(`/api/health`·`/api/ready`만 예외).
- **`FORGE_REQUIRE_AUTH=1` 설정(fail-closed 기동).** 기본은 `False`라, 토큰을 깜빡 빼먹어도 서버가 조용히 무인증으로 뜬다. `1`로 켜면 `auth_token`이 없을 때 기동 자체를 거부한다(`assert_startup_auth`). 원격 배포에서는 이 fail-closed가 실수 방지선이다.
- **`FORGE_ALLOWED_ORIGINS` 좁히기.** 미설정이면 CORS가 `*`로 열린다. 실제 접속 도메인만 콤마로 나열해 cross-origin 접근을 막는다.
- **앞단에 Cloudflare Access / Zero Trust / VPN을 둔다.** 앱 토큰은 defense-in-depth일 뿐이고, 터널·네트워크 계층 인증이 1차 방벽이다. FORGE를 공개 인터넷에 직접 노출하지 않는다.
- **가능하면 loopback(`127.0.0.1`)에 바인딩한다.** uvicorn이 `0.0.0.0`에 붙으면 같은 LAN의 다른 기기가 터널을 우회해 직접 붙을 수 있다. Cloudflare Access 같은 터널을 앞단에 두는 구성에서는 uvicorn을 loopback에만 바인딩해 우회 경로를 없앤다.
- **`WORKSPACE`를 좁은 프로젝트 디렉터리로.** `.env.example` 기본값은 `/Users/insub/Desktop` 같은 넓은 개인 경로다. 워크스페이스는 파일 도구와 host 쓰기 방벽이 쓰기를 제한하는 경계이자 host 모드 `_run_host`의 실행 위치이기도 하다. 넓게 잡을수록 사고 반경이 그대로 커진다. 실제 작업할 단일 프로젝트 폴더로 좁힌다.
- **`sandbox_mode=host`는 호스트 전체 접근임을 이해한다.** host 모드는 bash를 컨테이너 없이 호스트에서 직접 실행한다. 파괴적 명령을 막는 `_DANGEROUS` 정규식 블랙리스트가 있지만, 모듈 주석이 밝히듯 변수 치환·`find -delete`·`python3 -c` 같은 우회에 취약하다. 블랙리스트는 방어의 전부가 아니라 최소 안전장치로만 본다.

## host 모드 쓰기 방벽은 macOS 전용

`host_write_guard`(기본 `True`)는 워크스페이스 밖 쓰기를 OS 레벨에서 막는 유일한 실질 방벽이다. 그런데 이건 macOS `sandbox-exec`에만 의존한다. `host_guard.available()`은 `sys.platform == "darwin"`이고 `/usr/bin/sandbox-exec`이 존재할 때만 `True`를 반환한다. 둘 중 하나라도 아니면 `wrap()`이 명령을 감싸지 않고 원본 그대로 돌려준다 — fail-open이다.

결과는 이렇다. Linux나 CI에서 host 모드를 켜면 쓰기 방벽이 무동작이 되고, 남는 방어는 우회 가능한 `_DANGEROUS` 블랙리스트뿐이다. 즉 Linux의 host 모드에는 사실상 쓰기 경계가 없다. bash가 그 프로세스 권한으로 워크스페이스 밖 어디든 쓸 수 있다.

그러니 Linux/CI에서는 `sandbox_mode=docker`를 쓴다(네트워크 차단·워크스페이스 마운트·리소스 상한으로 격리된다). docker를 못 쓰는 환경이라면 host 모드를 외부에 노출하지 않는다. host 모드의 풀파워는 macOS의 `sandbox-exec` 방벽을 전제로 한 옵트인이다.

## 참고

- 신뢰 경계 전반: [docs/core/trust-boundary.md](../core/trust-boundary.md)
- 알려진 위험 목록: [docs/status/work-status.md](../status/work-status.md)의 "알려진 위험" 절
