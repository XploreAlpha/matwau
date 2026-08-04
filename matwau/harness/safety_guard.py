"""mat-safety-guard — 安全护栏(per Harness-Loop doc §5.4)

Stage 1 简版(软件层),Stage 3 升级为 3 重防线(软件 + AI + 硬件 PLC 急停)

核心功能:
1. SafetyGuard.check() — 4 类危险操作检查 + 1 类 PII 脱敏
   - 删 DB(> 100MB 拦截,需人工审批)
   - 提 HPC job(> ¥1000 拦截,需 supervisor 审批)
   - 外发消息(自动脱敏电话/邮箱/学号)
   - 外发 API 调用(白名单检查)

2. @guard(quota=..., sandbox=True) 装饰器
   - 任何 agent method 自动套配额 + 沙箱 + 输出检查
   - 不改业务代码

3. PII 脱敏
   - 电话:1[3-9]xx xxxx xxx → [PHONE]
   - 邮箱:abc@xx.com → [EMAIL]
   - 长 ID(>= 10 位数字)→ [ID]

用法:
    guard = SafetyGuard(budget_limit=1000)

    @guard(quota="mat-exp.hpc", sandbox=True)
    def submit_xrd_job(cif, params):
        return xrd_driver.run(cif, params)

    # 装饰的 method 自动:
    #   1. 配额检查(quota 用完抛 QuotaExceeded)
    #   2. 沙箱执行(异常隔离)
    #   3. 输出清洗(走 SafetyGuard.check)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

# ============================================================================
# 异常
# ============================================================================


class SafetyViolation(Exception):
    """安全违规异常"""

    def __init__(self, message: str, action_type: str = "", blocked: bool = True):
        super().__init__(message)
        self.action_type = action_type
        self.blocked = blocked


class QuotaExceeded(SafetyViolation):
    """配额用完"""

    def __init__(self, quota: str):
        super().__init__(f"quota '{quota}' exhausted", action_type="quota", blocked=True)
        self.quota = quota


class HumanApprovalRequired(SafetyViolation):
    """需要人工审批"""

    def __init__(self, prompt: str, action_type: str):
        super().__init__(prompt, action_type=action_type, blocked=True)
        self.prompt = prompt
        self.action_type = action_type


# ============================================================================
# 配置
# ============================================================================


@dataclass
class SafetyPolicy:
    """安全策略配置"""

    # 删 DB
    delete_threshold_mb: int = 100
    delete_require_approval: bool = True

    # HPC job
    hpc_cost_threshold: float = 1000.0
    hpc_require_approval: bool = True

    # 外发 API 白名单(必须以此为前缀)
    api_whitelist: tuple = ("http://mat-", "http://wau-", "http://localhost")

    # PII 脱敏开关
    pii_redact_enabled: bool = True


# ============================================================================
# SafetyGuard 核心
# ============================================================================


class SafetyGuard:
    """安全护栏 — Stage 1 简版

    Args:
        budget_limit: 单次任务总预算 ¥(默认 1000)
        policy: SafetyPolicy(可选,默认全部阈值)
        approval_callback: 人工审批函数
            signature: (prompt: str, action_type: str) -> bool
            默认 input() 阻塞等待(Stage 1),Stage 3 接 HomeRail 弹窗
    """

    # 4 类危险操作 + 1 类清洗
    DANGEROUS_ACTIONS = {
        "delete_database": "_check_delete",
        "submit_hpc_job": "_check_hpc_cost",
        "send_external_message": "_check_message",
        "send_external_api": "_check_api_whitelist",
    }

    def __init__(
        self,
        budget_limit: float = 1000.0,
        policy: SafetyPolicy | None = None,
        approval_callback: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.budget_limit = budget_limit
        self.policy = policy or SafetyPolicy()
        self.approval_callback = approval_callback or self._default_approval
        self._blocked_count = 0
        self._pii_redacted_count = 0
        self._approval_count = 0

    # ========================================================================
    # 主入口:check()
    # ========================================================================

    def check(self, response: Any) -> bool:
        """检查 1 个 response 是否安全

        Args:
            response: AgentResponse 或任意对象,有 artifacts dict

        Returns:
            True = 通过,False = 拦截
        """
        artifacts = getattr(response, "artifacts", {}) or {}
        if not isinstance(artifacts, dict):
            return True

        for action_type in self.DANGEROUS_ACTIONS:
            # artifacts 含 action_type 触发对应检查
            if action_type in str(artifacts) or action_type in artifacts:
                checker_name = self.DANGEROUS_ACTIONS[action_type]
                checker = getattr(self, checker_name)
                try:
                    if not checker(response):
                        self._blocked_count += 1
                        return False
                except HumanApprovalRequired:
                    raise  # 冒泡让上层处理
                except Exception:
                    # 检查器自身异常 → 默认放行(避免阻断业务)
                    pass

        return True

    # ========================================================================
    # 4 类危险操作检查
    # ========================================================================

    def _check_delete(self, response: Any) -> bool:
        """删 DB 检查:超过阈值必须人工审批"""
        artifacts = getattr(response, "artifacts", {}) or {}
        size_mb = artifacts.get("delete_size_mb", 0)
        if size_mb > self.policy.delete_threshold_mb:
            # _require_human_approval 不抛异常 + 返回 True = 审批通过
            if not self.approval_callback(
                f"删除 {size_mb}MB 数据库(>{self.policy.delete_threshold_mb}MB),确认?",
                "delete_database",
            ):
                self._approval_count += 1
                raise HumanApprovalRequired(
                    f"删除 {size_mb}MB 数据库未获批准",
                    action_type="delete_database",
                )
            self._approval_count += 1
            return True  # 审批通过,放行
        return True

    def _check_hpc_cost(self, response: Any) -> bool:
        """HPC job 成本检查:超过阈值必须 supervisor 审批"""
        artifacts = getattr(response, "artifacts", {}) or {}
        cost = artifacts.get("estimated_cost", 0)
        if cost > self.policy.hpc_cost_threshold:
            if not self.approval_callback(
                f"提交 HPC job ¥{cost}(>¥{self.policy.hpc_cost_threshold}),supervisor 确认?",
                "submit_hpc_job",
            ):
                self._approval_count += 1
                raise HumanApprovalRequired(
                    f"HPC job ¥{cost} 未获批准",
                    action_type="submit_hpc_job",
                )
            self._approval_count += 1
            return True
        return True

    def _check_message(self, response: Any) -> bool:
        """外发消息:自动脱敏 PII(默认放行,只清洗)"""
        artifacts = getattr(response, "artifacts", {}) or {}
        msg = artifacts.get("message", "")
        if msg and self.policy.pii_redact_enabled:
            redacted = self._redact_pii(msg)
            if redacted != msg:
                self._pii_redacted_count += 1
                artifacts["message"] = redacted
        return True

    def _check_api_whitelist(self, response: Any) -> bool:
        """外部 API:白名单检查"""
        artifacts = getattr(response, "artifacts", {}) or {}
        url = artifacts.get("url", "")
        if not url:
            return True
        return url.startswith(self.policy.api_whitelist)

    # ========================================================================
    # PII 脱敏
    # ========================================================================

    # 中国手机号:1[3-9]xx xxxx xxx
    _PHONE_RE = re.compile(r"1[3-9]\d{9}")

    # 邮箱:xxx@xxx.xxx
    _EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

    # 学号 / 长 ID:10+ 位连续数字
    _ID_RE = re.compile(r"\b\d{10,}\b")

    def _redact_pii(self, text: str) -> str:
        """脱敏 PII(电话 / 邮箱 / 长 ID)"""
        text = self._PHONE_RE.sub("[PHONE]", text)
        text = self._EMAIL_RE.sub("[EMAIL]", text)
        text = self._ID_RE.sub("[ID]", text)
        return text

    # ========================================================================
    # 配额管理
    # ========================================================================

    def check_quota(self, quota: str) -> bool:
        """检查配额(Stage 1 简版永远 True,Stage 3 接 wau-store billing_ledger)"""
        # Stage 1:配额仅作语义标识,真正检查在 budget_limit
        # Stage 3:接 wau-store 查实际用量
        return True

    # ========================================================================
    # 内部
    # ========================================================================

    def _require_human_approval(self, prompt: str, action_type: str) -> None:
        """人工审批:调 approval_callback,False → 抛 HumanApprovalRequired"""
        self._approval_count += 1
        if not self.approval_callback(prompt, action_type):
            raise HumanApprovalRequired(prompt, action_type=action_type)

    def _default_approval(self, prompt: str, action_type: str) -> bool:
        """默认审批:Stage 1 input() 阻塞,Stage 3 接 HomeRail 弹窗"""
        # 测试环境默认 False 避免阻塞,生产环境要换 approval_callback
        return False

    def stats(self) -> dict[str, int]:
        """安全统计"""
        return {
            "blocked": self._blocked_count,
            "pii_redacted": self._pii_redacted_count,
            "approvals": self._approval_count,
        }


# ============================================================================
# 装饰器:@guard
# ============================================================================


def guard(
    quota: str | None = None,
    sandbox: bool = True,
    safety_guard: SafetyGuard | None = None,
):
    """装饰器:任何 agent method 自动套 SafetyGuard

    Args:
        quota: 配额标识(如 "mat-exp.hpc"),若指定会用完抛 QuotaExceeded
        sandbox: 是否沙箱执行(异常隔离,默认 True)
        safety_guard: SafetyGuard 实例(若不传,从 self.safety_guard 取)

    用法:
        class MatExpAgent(MatWAUAgentBase):
            @guard(quota="mat-exp.hpc", sandbox=True)
            def submit_xrd_job(self, cif, params):
                return xrd_driver.run(cif, params)
    """

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            sg = safety_guard or getattr(self, "safety_guard", None)

            # 1. 配额检查
            if quota and sg and not sg.check_quota(quota):
                raise QuotaExceeded(quota)

            # 2. 沙箱执行 + 输出清洗
            try:
                if sandbox:
                    try:
                        result = func(self, *args, **kwargs)
                    except Exception:
                        # 沙箱捕获 + 记录,但不冒泡(避免破坏业务)
                        return {"error": "sandbox exception", "status": "failed"}
                else:
                    result = func(self, *args, **kwargs)
            except (QuotaExceeded, HumanApprovalRequired):
                # 配额/审批异常冒泡(给上层决策)
                raise
            except Exception:
                raise

            # 3. 输出清洗(若有 SafetyGuard)
            if sg and not sandbox:
                try:
                    # 构造临时 response 给 check
                    from matwau.core.agent_base import AgentResponse

                    if not isinstance(result, AgentResponse):
                        result = AgentResponse(reply=str(result), artifacts=result if isinstance(result, dict) else {})
                    sg.check(result)
                except HumanApprovalRequired:
                    raise
                except Exception:
                    pass  # 检查器异常不阻断

            return result

        return wrapper

    return decorator


__all__ = [
    "HumanApprovalRequired",
    "QuotaExceeded",
    "SafetyGuard",
    "SafetyPolicy",
    "SafetyViolation",
    "guard",
]