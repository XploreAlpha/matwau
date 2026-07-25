"""MatWAU-AgentBase 单元测试

测试覆盖(per MatWAU-Harness-Loop-工程心法实践.md §4 + §8 验收):
1. ✅ Inner Loop 4 步(perceive → plan → act → reflect)按序执行
2. ✅ 11 agent 继承基类后,只实现 system_prompt() + act() 即可跑
3. ✅ 5 大 Harness 部件可注入,缺省时走 fallback
4. ✅ 终止条件 1:confidence > 0.85 → 跳出循环
5. ✅ 终止条件 2:tools 为空 → 跳出循环
6. ✅ 终止条件 3:达 max_iterations 上限
7. ✅ Outer Loop 失败回调:confidence < 0.5 触发 failure_callback
8. ✅ SafetyGuard 拦截时 response.reply 被改写
9. ✅ StateStore.persist 被调用(lineage 写入)
10. ✅ 多轮迭代,best_response 返回最高 confidence 的版本
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 把 matwau/ 加进 sys.path(项目本地包,无 setup.py 也能 import)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from matwau.core.agent_base import (  # noqa: E402
    AgentRequest,
    AgentResponse,
    ContextManager,
    EvalHarness,
    MatWAUAgentBase,
    SafetyGuard,
    StateStore,
    ToolRegistry,
)


# ============================================================================
# 测试用 Harness 部件 mock
# ============================================================================


class MockContextManager(ContextManager):
    """Mock ContextManager — 简单拼装"""

    def __init__(self, ret: dict = None, raise_on_call: bool = False):
        self.ret = ret or {
            "messages": [{"role": "user", "content": "mocked"}],
            "estimated_tokens": 100,
        }
        self.call_count = 0
        self.raise_on_call = raise_on_call

    def assemble(self, system_prompt, user_message, artifacts, history, **kwargs):
        self.call_count += 1
        if self.raise_on_call:
            raise RuntimeError("mock context manager error")
        return {**self.ret, "system_prompt": system_prompt, "user_message": user_message}


class MockToolRegistry(ToolRegistry):
    """Mock ToolRegistry — 返回固定工具列表"""

    def __init__(self, tools: list = None, raise_on_call: bool = False):
        self.tools = tools or ["tool1"]
        self.call_count = 0
        self.raise_on_call = raise_on_call

    def select_tools(self, ctx):
        self.call_count += 1
        if self.raise_on_call:
            raise RuntimeError("mock tool registry error")
        return self.tools


class MockStateStore(StateStore):
    """Mock StateStore — 记录 persist + load_history 调用"""

    def __init__(self, history: list = None, raise_on_load: bool = False):
        self.history = history or []
        self.persisted: list = []  # [(run_id, response), ...]
        self.raise_on_load = raise_on_load

    def persist(self, run_id, response):
        self.persisted.append((run_id, response))

    def load_history(self, run_id):
        if self.raise_on_load:
            raise RuntimeError("mock state store load error")
        return self.history


class MockSafetyGuard(SafetyGuard):
    """Mock SafetyGuard — 默认通过,可选拦截"""

    def __init__(self, block: bool = False, raise_on_call: bool = False):
        self.block = block
        self.check_count = 0
        self.raise_on_call = raise_on_call

    def check(self, response):
        self.check_count += 1
        if self.raise_on_call:
            raise RuntimeError("mock safety guard error")
        return not self.block


class MockEvalHarness(EvalHarness):
    """Mock EvalHarness — 返回固定分数"""

    def __init__(self, score: float = 0.9, raise_on_call: bool = False):
        self.score = score
        self.eval_count = 0
        self.raise_on_call = raise_on_call

    def self_eval(self, response):
        self.eval_count += 1
        if self.raise_on_call:
            raise RuntimeError("mock eval harness error")
        return self.score


# ============================================================================
# 测试用具体 agent 子类
# ============================================================================


class DummyAgent(MatWAUAgentBase):
    """最简 agent:act() 返回固定 reply + 高 confidence(模拟已知成功)"""

    name = "dummy-agent"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.act_call_count = 0
        self.act_log = []  # 记录每次 act() 调用时的 ctx + tools

    def system_prompt(self) -> str:
        return "你是测试 agent,只回 'ok'"

    def act(self, ctx, tools):
        self.act_call_count += 1
        self.act_log.append((ctx, tools))
        # confidence=0.95 → 触发"终止条件 1" → 1 轮结束
        return AgentResponse(reply="ok", artifacts={"i": self.act_call_count}, confidence=0.95)


class MultiIterAgent(MatWAUAgentBase):
    """多轮迭代 agent:前 N 轮 confidence < 阈值,第 N+1 轮达阈值"""

    name = "multi-iter-agent"  # 必须显式设 name(否则 __init__ 抛 ValueError)

    def __init__(self, success_at_iter: int = 3, **kwargs):
        super().__init__(**kwargs)
        self.success_at_iter = success_at_iter
        self.act_call_count = 0

    def system_prompt(self) -> str:
        return "多轮迭代测试 agent"

    def act(self, ctx, tools):
        self.act_call_count += 1
        if self.act_call_count >= self.success_at_iter:
            confidence = 0.95  # 超过阈值 0.85
        else:
            confidence = 0.3  # 低于阈值,继续迭代
        return AgentResponse(reply=f"iter{self.act_call_count}", confidence=confidence)


class FailingActAgent(MatWAUAgentBase):
    """act() 抛异常的 agent — 测试基类是否让异常冒泡"""

    name = "failing-act-agent"

    def system_prompt(self) -> str:
        return "失败测试"

    def act(self, ctx, tools):
        raise RuntimeError("act() intentional failure")


class UnnamedAgent(MatWAUAgentBase):
    """没设 name 的 agent — 测试构造时校验"""

    name = ""  # 故意空

    def system_prompt(self) -> str:
        return "test"

    def act(self, ctx, tools):
        return AgentResponse(reply="ok")


# ============================================================================
# 1. 基础继承 + 必填字段校验
# ============================================================================


def test_dummy_agent_basic_run():
    """最简用例:无 Harness 部件注入,跑通 1 轮"""
    agent = DummyAgent()
    req = AgentRequest(run_id="run-001", message="hello")

    response = agent.run(req)

    assert response.reply == "ok"
    assert agent.act_call_count == 1


def test_name_required():
    """name 未设置 → ValueError"""
    with pytest.raises(ValueError, match="必须定义类属性 name"):
        UnnamedAgent()


def test_system_prompt_required():
    """system_prompt() 是 abstractmethod,子类必须实现"""
    # 这里通过 type error 间接验证
    with pytest.raises(TypeError):
        MatWAUAgentBase()  # type: ignore[abstract]


# ============================================================================
# 2. Inner Loop 4 步执行顺序
# ============================================================================


def test_inner_loop_steps_called_in_order():
    """perceive → plan → act → reflect 必须按序执行(DummyAgent + EvalHarness 跑 2 轮:第 1 轮建立 best,第 2 轮无进步 break)"""
    cm = MockContextManager()
    tr = MockToolRegistry()
    ss = MockStateStore()
    sg = MockSafetyGuard()
    eh = MockEvalHarness(score=0.5)

    agent = DummyAgent(
        context_manager=cm, tool_registry=tr, state_store=ss, safety_guard=sg, eval_harness=eh
    )
    req = AgentRequest(run_id="run-002", message="test")

    response = agent.run(req)

    # EvalHarness 注入 + confidence=0.5(永远不达 0.85)→ 跑 2 轮后触发"无进步"终止
    assert cm.call_count == 2
    assert tr.call_count == 2
    assert agent.act_call_count == 2
    assert eh.eval_count == 2
    assert sg.check_count == 2
    assert len(ss.persisted) == 2
    # reflect 写 confidence = eval_harness 返回值
    assert response.confidence == 0.5


# ============================================================================
# 3. 终止条件 1:confidence > 0.85 → 跳出循环
# ============================================================================


def test_terminate_when_confidence_high():
    """第 1 轮 confidence = 0.95,立即跳出,只跑 1 次 act"""
    eh = MockEvalHarness(score=0.95)
    agent = DummyAgent(eval_harness=eh)

    req = AgentRequest(run_id="run-003", message="test")
    response = agent.run(req)

    assert agent.act_call_count == 1  # 只跑 1 次
    assert response.confidence == 0.95


# ============================================================================
# 4. 终止条件 2:tools 为空 → 跳出循环
# ============================================================================


def test_terminate_when_no_tools():
    """plan() 返回空 → 跳出"""
    tr = MockToolRegistry(tools=[])  # 无工具
    agent = DummyAgent(tool_registry=tr)

    req = AgentRequest(run_id="run-004", message="test")
    response = agent.run(req)

    assert agent.act_call_count == 1  # 只跑 1 次


# ============================================================================
# 5. 终止条件 3:达 max_iterations 上限
# ============================================================================


def test_terminate_when_max_iter_reached():
    """iter 上限 5,每轮 confidence=0.3 → 跑满 5 次,返回 best_response"""
    agent = MultiIterAgent(success_at_iter=999)  # 永远不到阈值
    agent.max_iterations = 5

    req = AgentRequest(run_id="run-005", message="test")
    response = agent.run(req)

    assert agent.act_call_count == 5  # 跑满上限
    # best_response 是最高 confidence 版本(每轮都 0.3,取首个)
    assert response.confidence == 0.3
    assert response.reply == "iter1"


# ============================================================================
# 6. 多轮迭代:第 3 轮 confidence 达阈值
# ============================================================================


def test_multi_iteration_success_at_third():
    """iter=3 时 confidence=0.95,跑 3 次 act 后跳出"""
    agent = MultiIterAgent(success_at_iter=3)
    agent.max_iterations = 5

    req = AgentRequest(run_id="run-006", message="test")
    response = agent.run(req)

    assert agent.act_call_count == 3
    assert response.confidence == 0.95
    assert response.reply == "iter3"


# ============================================================================
# 7. Outer Loop 失败回调
# ============================================================================


def test_failure_callback_triggered():
    """confidence < 0.5 + failure_callback 已注入 → 触发(每轮 reflect 都触发,2 轮)"""
    failures = []

    def cb(req, resp):
        failures.append((req.run_id, resp.reply))

    eh = MockEvalHarness(score=0.3)  # < 0.5
    agent = DummyAgent(eval_harness=eh, failure_callback=cb)

    req = AgentRequest(run_id="run-007", message="test")
    agent.run(req)

    # 跑 2 轮(第 1 轮 + 第 2 轮"无进步"终止),每轮 reflect 都触发失败回调
    assert len(failures) == 2
    assert all(f == ("run-007", "ok") for f in failures)


def test_no_failure_callback_when_confidence_high():
    """confidence > 0.5 → 不触发 failure_callback"""
    failures = []

    def cb(req, resp):
        failures.append((req.run_id, resp.reply))

    eh = MockEvalHarness(score=0.9)  # > 0.5
    agent = DummyAgent(eval_harness=eh, failure_callback=cb)

    req = AgentRequest(run_id="run-008", message="test")
    agent.run(req)

    assert len(failures) == 0


# ============================================================================
# 8. SafetyGuard 拦截
# ============================================================================


def test_safety_guard_blocks_response():
    """SafetyGuard.block=True → reply 被改写 + confidence 置 0"""
    sg = MockSafetyGuard(block=True)
    agent = DummyAgent(safety_guard=sg)

    req = AgentRequest(run_id="run-009", message="test")
    response = agent.run(req)

    assert "[BLOCKED by SafetyGuard]" in response.reply
    assert response.confidence == 0.0


def test_safety_guard_allows_response():
    """SafetyGuard.block=False → reply 保持原样"""
    sg = MockSafetyGuard(block=False)
    agent = DummyAgent(safety_guard=sg)

    req = AgentRequest(run_id="run-010", message="test")
    response = agent.run(req)

    assert response.reply == "ok"
    assert "[BLOCKED" not in response.reply


# ============================================================================
# 9. StateStore.persist 被调用(lineage 写入)
# ============================================================================


def test_state_store_persist_called():
    """run() 后 StateStore.persist 收到 (run_id, response)"""
    ss = MockStateStore()
    agent = DummyAgent(state_store=ss)

    req = AgentRequest(run_id="run-011", message="test", artifacts={"x": 1})
    response = agent.run(req)

    assert len(ss.persisted) == 1
    run_id, stored_resp = ss.persisted[0]
    assert run_id == "run-011"
    assert stored_resp.reply == "ok"
    assert stored_resp.artifacts == {"i": 1}


# ============================================================================
# 10. Harness 部件抛异常 → 不让循环崩
# ============================================================================


def test_context_manager_raises_falls_back():
    """ContextManager.assemble() 抛异常 → 基类 catch + warning,跑通"""
    cm = MockContextManager(raise_on_call=True)
    agent = DummyAgent(context_manager=cm)

    req = AgentRequest(run_id="run-012", message="test")
    response = agent.run(req)  # 不应该崩

    # fallback ctx 让 act() 仍能跑
    assert agent.act_call_count == 1
    assert response.reply == "ok"


def test_safety_guard_raises_continues():
    """SafetyGuard.check() 抛异常 → 基类 catch + warning,不阻断"""
    sg = MockSafetyGuard(raise_on_call=True)
    agent = DummyAgent(safety_guard=sg)

    req = AgentRequest(run_id="run-013", message="test")
    response = agent.run(req)  # 不应该崩

    assert response.reply == "ok"
    assert "[BLOCKED" not in response.reply


# ============================================================================
# 11. AgentRequest / AgentResponse 数据类
# ============================================================================


def test_agent_request_defaults():
    """AgentRequest 默认值"""
    req = AgentRequest(run_id="r1", message="hi")
    assert req.artifacts == {}
    assert req.context == {}
    assert req.budget is None
    assert req.metadata == {}


def test_agent_response_defaults():
    """AgentResponse 默认值"""
    resp = AgentResponse()
    assert resp.reply == ""
    assert resp.artifacts == {}
    assert resp.confidence == 0.0
    assert resp.cost == 0.0
    assert resp.lineage_id is None
    assert resp.error is None


# ============================================================================
# 12. __repr__ 展示 Harness 部件注入情况
# ============================================================================


def test_repr_shows_injected_parts():
    """__repr__ 显示已注入的 Harness 部件"""
    cm = MockContextManager()
    sg = MockSafetyGuard()

    agent = DummyAgent(context_manager=cm, safety_guard=sg)
    repr_str = repr(agent)

    assert "dummy-agent" in repr_str
    assert "context_manager=✓" in repr_str
    assert "safety_guard=✓" in repr_str
    assert "tool_registry=✓" not in repr_str  # 未注入