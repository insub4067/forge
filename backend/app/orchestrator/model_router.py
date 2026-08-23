from ..config import settings


class ModelRouter:
    """올인원 구조의 모델 선택. 역할은 Developer(통합)·Vision·Chat 3개.

    비용 원칙: 기본은 flash. Developer는 설계+구현+자체검증을 하므로 thinking medium을 켠다.
    실패 시에만 pro+think-high로 승격한다(escalate) — 90% 비용을 아끼며 품질을 확보.
    정책은 런타임에 get_policy/update_policy로 조회·변경할 수 있다.
    """

    def __init__(self):
        self._policy: dict[str, dict] = {
            # 통합 Developer — 설계 + 구현 + 자체검증(Reviewer/Debugger 역할 내재)
            "developer": {
                "model": settings.developer_model or settings.coder_model or "deepseek-v4-flash",
                "thinking": True,
                "reasoning_effort": "medium",
            },
            "vision": {
                "model": settings.vision_model or "deepseek-v4-flash-vision-exp",
                "thinking": False,
                "reasoning_effort": "low",
            },
        }
        # 실패 시 승격 모델(pro)
        self.developer_pro_model = settings.developer_pro_model or settings.deep_seek_model or "deepseek-v4-pro"
        # compaction 등 저비용 유틸 요약용 flash 모델
        self.utility_model = "deepseek-v4-flash"

    def select_model(self, agent_type: str, retry_count: int = 0,
                     complexity: str = "normal", escalate: bool = False) -> dict:
        base = dict(self._policy.get(agent_type, self._policy["developer"]))

        # Developer 승격: 실패 재시도(escalate) 또는 항상-pro 옵션일 때 pro+think-high.
        if agent_type == "developer" and (escalate or settings.developer_pro):
            base.update({
                "model": self.developer_pro_model,
                "thinking": True,
                "reasoning_effort": "high",
            })
        return base

    def get_policy(self) -> dict:
        return {"roles": {k: dict(v) for k, v in self._policy.items()},
                "developer_pro_model": self.developer_pro_model}

    def update_policy(self, role: str, model: str | None = None,
                      thinking: bool | None = None, reasoning_effort: str | None = None) -> bool:
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
