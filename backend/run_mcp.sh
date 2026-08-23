#!/usr/bin/env bash
# FORGE MCP 서버 실행 래퍼 — 어느 cwd에서 호출해도 backend에서 모듈이 로드되게 한다.
# MCP 클라이언트는 이 스크립트 경로만 지정하면 된다(cwd 지정 불필요).
cd "$(dirname "$0")" && exec .venv/bin/python -m app.mcp.server
