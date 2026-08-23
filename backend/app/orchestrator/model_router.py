from ..config import settings


class ModelRouter:
    """Agent 타입과 태스크 상태를 기반으로 모델·thinking·effort를 선택한다.

    정책은 런타임에 get_policy/update_policy로 조회·변경할 수 있다.
    """

    def __init__(self):
        self._policy: dict[str, dict] = {
            "planner": {
                "model": settings.planner_model or "deepseek-v4-flash",
                "thinking": True,
                "reasoning_effort": "medium",
            },
            "coder": {
                "model": settings.coder_model or "deepseek-v4-flash",
                "thinking": False,
                "reasoning_effort": "low",
            },
            "reviewer": {
                "model": settings.reviewer_model or "deepseek-v4-flash",
                "thinking": True,
                "reasoning_effort": "medium",
            },
            "debugger": {
                "model": settings.debugger_model or "deepseek-v4-flash",
                "thinking": False,
                "reasoning_effort": "low",
            },
            "vision": {
                "model": settings.vision_model or "deepseek-v4-flash-vision-exp",
                "thinking": False,
                "reasoning_effort": "low",
            },
            "chat": {
                "model": settings.chat_model or "deepseek-v4-flash",
                "thinking": False,
                "reasoning_effort": "low",
            },
        }
        self.debugger_pro_model = settings.deep_seek_model or "deepseek-v4-pro"
        self.planner_pro_model = settings.planner_pro_model or settings.deep_seek_model or "deepseek-v4-pro"
        self.triage_model = settings.triage_model or "deepseek-v4-flash"

    def select_model(
        self,
        agent_type: str,
        retry_count: int = 0,
        complexity: str = "normal",
    ) -> dict:
        base = dict(self._policy.get(agent_type, self._policy["coder"]))

        if agent_type == "debugger" and (retry_count >= 3 or complexity == "high"):
            base.update(
                {
                    "model": self.debugger_pro_model,
                    "thinking": True,
                    "reasoning_effort": "high",
                }
            )

        # planner는 flash가 기본. 복잡한 작업(triage 판정)일 때만 pro로 승격.
        # planner_flash 실험 플래그가 켜지면 승격을 건너뛰고 flash 유지(비용 실험).
        if agent_type == "planner" and complexity == "high" and not settings.planner_flash:
            base.update(
                {
                    "model": self.planner_pro_model,
                    "thinking": True,
                    "reasoning_effort": "high",
                }
            )

        return base

    def get_policy(self) -> dict:
        return {
            "roles": {k: dict(v) for k, v in self._policy.items()},
            "debugger_pro_model": self.debugger_pro_model,
        }

    def update_policy(
        self,
        role: str,
        model: str | None = None,
        thinking: bool | None = None,
        reasoning_effort: str | None = None,
    ) -> bool:
        if role not in self._policy:
            return False
        p = self._policy[role]
        if model is not None and model.strip():
            p["model"] = model.strip()
        if thinking is not None:
            p["thinking"] = bool(thinking)
        if reasoning_effort is not None and reasoning_effort.strip():
            p["reasoning_effort"] = reasoning_effort.strip()
        return True
