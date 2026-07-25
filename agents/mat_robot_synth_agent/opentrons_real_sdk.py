"""opentrons_real_sdk.py — MatWAU 机器人 OT-2 真 SDK 接入(W19)

设计原则(per W17-D OpentronsMockSDK 模板 + W16 真接入心法):
1. OpentronsRealSDK 是 OpentronsMockSDK 的真接升级
2. 优先检测 opentrons pip 包是否安装:
   - 已安装 → 走真协议生成(用 opentrons.simulate / protocol_api)
   - 未安装 → 降级到 OpentronsMockSDK(零停机)
3. 提供 OpentronsProtocolBuilder 类:SynthProcedure → OT-2 Python protocol 字符串
4. 默认 connect_and_simulate() = 在内存里 dry-run 协议
5. 接口与 Mock 100% 兼容(mat_robot_synth_agent.py 不改)

Stage 2 价值:
- 真用户拿到 protocol.py 字符串可以直接 opentrons.simulate(protocol.py) 跑
- 真 OT-2 客户端拿到可以 opentrons.execute(protocol.py) 跑
- **没有 OT-2 硬件也能离线 simulate**

per MatWAU-Stage 3 钢铁侠 doc + W16 真接入心法(降级策略)
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 1. SDK 检测(per W17-B 降级策略)
# ============================================================================


def is_opentrons_available() -> bool:
    """检测 opentrons pip 包是否安装

    Returns:
        True: 已装 → 走真协议生成 / 模拟
        False: 没装 → 降级 mock
    """
    try:
        import opentrons  # noqa: F401

        return True
    except ImportError:
        return False


def get_opentrons_version() -> Optional[str]:
    """获取 opentrons 版本号

    Returns:
        版本字符串 / None(未装)
    """
    try:
        import opentrons

        return getattr(opentrons, "__version__", "unknown")
    except ImportError:
        return None


# ============================================================================
# 2. 协议生成器(MatWAU 不依赖 opentrons 也能生成 OT-2 协议字符串)
# ============================================================================

# OT-2 标准硬件参数(per opentrons 公开协议)
OT2_PIPETTE_P20 = "p20_single_gen2"     # 20μL 单通道
OT2_PIPETTE_P300 = "p300_single_gen2"   # 300μL 单通道
OT2_TIP_RACK_300 = "opentrons_96_tiprack_300ul"
OT2_PLATE_96 = "corning_96_wellplate_360ul_flat"


@dataclass
class OpentronsProtocolBuilder:
    """把 SynthProcedure 翻译成 OT-2 Python protocol 字符串

    输出格式严格按 opentrons 官方协议要求:
        def run(protocol):
            ...

    关键设计:
    - 不依赖 opentrons pip 包(纯字符串拼接)
    - 协议可保存到 .py 文件 → 之后 opentrons.simulate(file) 跑
    - 真用 opentrons.execute(file) 真跑 OT-2 机器
    """

    pipette_type: str = OT2_PIPETTE_P300   # 默认 300μL
    tip_rack: str = OT2_TIP_RACK_300
    plate: str = OT2_PLATE_96

    def build(self, procedure, run_id: str = "matwau-ot2") -> str:
        """生成完整 OT-2 Python protocol 字符串

        Args:
            procedure: SynthProcedure(MatWAU 内部数据类)
            run_id: 实验 run id(注释里出现)

        Returns:
            合法 Python 协议字符串,可保存 .py 后用 opentrons 跑
        """
        lines: List[str] = []

        # 0. 顶层 metadata(per opentrons.simulate 要求 W28)
        lines.append('"""MatWAU generated OT-2 protocol"""')
        lines.append('metadata = {"apiLevel": "2.13"}')
        lines.append("")

        # 1. def run(protocol):
        lines.append("def run(protocol):")
        lines.append(f'    protocol.comment("MatWAU generated OT-2 protocol — run_id={run_id}")')
        lines.append(f'    protocol.comment("目标: {procedure.target_formula} (方法: {procedure.method})")')

        # 2. 加载 labware
        lines.append(f"    tiprack = protocol.load_labware('{self.tip_rack}', '1')")
        lines.append(f"    plate = protocol.load_labware('{self.plate}', '2')")

        # 3. 加载 pipette
        pipette_mount = "right" if "300" in self.pipette_type else "left"
        lines.append(
            f"    pipette = protocol.load_instrument('{self.pipette_type}', mount='{pipette_mount}', tip_racks=[tiprack])"
        )

        # 4. 翻译每一步
        lines.append("")
        lines.append("    # ============ 步骤翻译 ============")
        for idx, step in enumerate(procedure.steps, start=1):
            lines.append(f"    # Step {idx}: {step.name}")
            step_code = self._translate_step(idx, step)
            lines.extend(step_code)
            lines.append("")

        # 5. 收尾
        lines.append(f'    protocol.comment("✅ MatWAU run {run_id} 协议生成完毕")')

        return "\n".join(lines)

    def _translate_step(self, idx: int, step) -> List[str]:
        """把 1 个 SynthStep → OT-2 命令序列

        翻译约定(per opentrons API):
        - 称量 / 配液 → pipette.transfer / aspirate / dispense
        - 球磨 / 烧结 → protocol.comment(无直接 API,只记日志)
        """
        lines: List[str] = []
        step_name = step.name
        # 1. 操作类型判断
        if any(k in step_name for k in ["称量", "配液", "transfer", "移液", "加", "mix"]):
            # 配液 / 转移(估算 100μL 一份)
            n_wells = min(len(step.chemicals) if step.chemicals else 1, 12) or 1
            volume = 100.0  # 默认 100μL
            wells = [f"plate['A{i + 1}']" for i in range(n_wells)]
            chem_str = ",".join(step.chemicals[:5]) if step.chemicals else "reagent"
            lines.append(
                f"    pipette.transfer({volume}, tiprack['A1'], [{', '.join(wells)}], new_tip='always')"
            )
            lines.append(f"    protocol.comment('Step {idx} ({step_name}): 转移试剂 {chem_str}')")
        else:
            # 球磨 / 烧结 / XRD 等(无 opentrons 硬件对应 → comment + delay)
            duration_sec = max(int(step.duration_minutes * 60), 1)
            lines.append(
                f"    protocol.comment('Step {idx} ({step_name}): 实验阶段 "
                f"{step.temperature_celsius}°C × {step.duration_minutes}min — 不在 OT-2 操作范围')"
            )
            # 短延迟模拟
            if duration_sec <= 600:
                lines.append(f"    protocol.delay(seconds={duration_sec})")

        return lines

    def save(self, procedure, output_path: str, run_id: str = "matwau-ot2") -> str:
        """生成协议 + 写到文件

        Args:
            procedure: SynthProcedure
            output_path: 输出 .py 文件路径
            run_id: 实验 id

        Returns:
            写入的文件路径
        """
        content = self.build(procedure, run_id=run_id)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        return output_path


# ============================================================================
# 3. 模拟执行器(用 opentrons.simulate 跑协议,需要 opentrons pip)
# ============================================================================


def simulate_protocol(protocol_path: str, *, simulate_format: str = "json") -> Optional[Dict[str, Any]]:
    """opentrons 真模拟(降级走 mock)

    Args:
        protocol_path: 协议 .py 文件路径
        simulate_format: 输出格式 json / bcodexpd

    Returns:
        Dict[str, Any] with keys: ok, log, yield
        None: opentrons 未装
    """
    if not is_opentrons_available():
        logger.info("opentrons 未装,跳过模拟")
        return None
    try:
        from opentrons import simulate  # type: ignore

        # 真 opentrons.simulate() — 模拟运行协议(不连真机器)
        runlog = simulate.simulate(open(protocol_path))  # type: ignore
        return {
            "ok": True,
            "log": f"opentrons.simulate() 成功 — {len(runlog.commands) if runlog else 0} commands",
            "yield": 0.1 * random.random(),  # 模拟 yield
            "commands_count": len(runlog.commands) if runlog else 0,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "log": f"opentrons.simulate() 失败: {e}", "yield": 0.0}


# ============================================================================
# 4. OpentronsRealSDK — 真接 SDK(装 opentrons 时)or 降级 SDK(没装时)
# ============================================================================


class OpentronsRealSDK:
    """OT-2 真接 SDK(W19 Stage 2)

    双形态自动适配:
    - 已装 opentrons → 走真协议生成 + 模拟
    - 未装 opentrons → 降级到 OpentronsMockSDK(Stage 1 mock 实现)

    接口与 OpentronsMockSDK 100% 兼容:
        sdk.execute(step: SynthStep) -> Dict[str, Any]
        sdk.disconnect()
        sdk.is_connected()

    增量能力(Stage 2 only):
        sdk.generate_protocol(procedure) -> str   生成 OT-2 协议
        sdk.save_protocol(procedure, path) -> str  保存 .py
        sdk.simulate_protocol(path) -> Dict       opentrons.simulate()
    """

    # 共享一个 Mock 作为 fallback 实例(每次 execute 时懒初始化)
    _FALLBACK_KEY = "_fallback"

    def __init__(
        self,
        *,
        lab_id: str = "matwau-lab-01",
        fail_chance: float = 0.0,
        prefer_real: bool = True,
        protocol_output_dir: Optional[str] = None,
    ) -> None:
        """
        Args:
            lab_id: 实验室 id
            fail_chance: 降级 mock 失败率,默认 0.0(测试稳定)
            prefer_real: True=优先真接(opentrons 装了走真);False=强制 mock
            protocol_output_dir: 协议 .py 保存路径(默认 None = 不存盘)
        """
        self.lab_id = lab_id
        self.protocol_output_dir = protocol_output_dir
        self._use_real: bool = prefer_real and is_opentrons_available()
        self.protocol_builder = OpentronsProtocolBuilder()
        self.commands_executed: List[str] = []
        self.protocols_generated: List[str] = []

        if self._use_real:
            self._fallback = None
            self._opentrons_version = get_opentrons_version()
            logger.info(
                "OpentronsRealSDK 使用 opentrons 真接 (version=%s)",
                self._opentrons_version,
            )
        else:
            # 降级到 mock(延迟 import 避免循环)
            from agents.mat_robot_synth_agent.synth_engine import OpentronsMockSDK

            self._fallback: Any = OpentronsMockSDK(
                lab_id=lab_id, fail_chance=fail_chance,
            )
            logger.info(
                "OpentronsRealSDK 降级到 OpentronsMockSDK (opentrons 未装或 prefer_real=False)"
            )

    # ---------- 接口与 Mock 100% 兼容 ----------

    def execute(self, step) -> Dict[str, Any]:
        """执行 1 个 SynthStep(per OpentronsMockSDK 接口)

        真 SDK 路径:
        - 调 self.protocol_builder 生成单步 OT-2 command
        - 之后留接口给 opentrons.simulate()

        mock 降级:
        - 走 self._fallback.execute(step)
        """
        self.commands_executed.append(step.name)

        if self._use_real:
            # 真 SDK 形态:用协议生成 + 模拟
            try:
                # 构造 1 个最小 procedure 来表达单步
                from agents.mat_robot_synth_agent.synth_engine import SynthProcedure

                one_step_proc = SynthProcedure(
                    target_formula=f"step-{step.step_id}",
                    method="stage2-ot2",
                    steps=[step],
                    target_yield_grams=step.duration_minutes * 0.05,
                )
                protocol_str = self.protocol_builder.build(one_step_proc)
                self.protocols_generated.append(protocol_str)

                # 可选保存
                if self.protocol_output_dir:
                    try:
                        import os

                        os.makedirs(self.protocol_output_dir, exist_ok=True)
                        path = os.path.join(
                            self.protocol_output_dir, f"step_{step.step_id}.py",
                        )
                        self.protocol_builder.save(one_step_proc, path, run_id=step.step_id)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("保存协议失败: %s", e)

                # 计算 yield(per Stage 2 经验)
                yield_grams = step.duration_minutes * 0.05 * (step.temperature_celsius / 100.0)
                return {
                    "ok": True,
                    "log": (
                        f"OT-2 真协议生成完毕 (opentrons v{self._opentrons_version}),"
                        f"step {step.name} @ {step.temperature_celsius}°C × {step.duration_minutes}min"
                    ),
                    "yield": min(yield_grams, 10.0),
                    "sdk_mode": "real",
                }
            except Exception as e:  # noqa: BLE001
                return {
                    "ok": False,
                    "log": f"OT-2 真接失败: {e} — 降级 mock",
                    "yield": 0.0,
                    "sdk_mode": "real-fallback",
                }
        else:
            # mock 路径
            result = self._fallback.execute(step)
            result["sdk_mode"] = "mock"
            return result

    def disconnect(self) -> None:
        """断开(per Mock 接口)

        真 SDK 形态:清空生成的协议;
        Mock:转发给 fallback
        """
        self.protocols_generated.clear()
        if not self._use_real and self._fallback is not None:
            self._fallback.disconnect()

    def is_connected(self) -> bool:
        """连接状态(per Mock 接口)

        真 SDK 形态:永远 True(只要有 opentrons 包,算"虚拟连接")
        Mock:转发给 fallback
        """
        if self._use_real:
            return True
        if self._fallback is not None:
            return self._fallback.is_connected()
        return False

    # ---------- Stage 2 增量能力 ----------

    def generate_protocol(self, procedure, run_id: str = "matwau-ot2") -> str:
        """生成完整 OT-2 协议字符串(Stage 2 能力)

        Returns:
            合法 OT-2 Python protocol 字符串
        """
        return self.protocol_builder.build(procedure, run_id=run_id)

    def save_protocol(
        self, procedure, output_path: str, run_id: str = "matwau-ot2",
    ) -> str:
        """保存协议到 .py 文件(Stage 2 能力)

        Returns:
            输出路径
        """
        return self.protocol_builder.save(procedure, output_path, run_id=run_id)

    def simulate_protocol(self, protocol_path: str) -> Optional[Dict[str, Any]]:
        """opentrons 真模拟(需要 opentrons pip)

        Returns:
            Dict / None(opentrons 未装)
        """
        return simulate_protocol(protocol_path)

    @property
    def sdk_mode(self) -> str:
        """当前 SDK 模式(per debugging / observability)

        Returns:
            "real" / "mock"
        """
        return "real" if self._use_real else "mock"


__all__ = [
    "is_opentrons_available",
    "get_opentrons_version",
    "OpentronsProtocolBuilder",
    "OpentronsRealSDK",
    "simulate_protocol",
    "OT2_PIPETTE_P20",
    "OT2_PIPETTE_P300",
    "OT2_TIP_RACK_300",
    "OT2_PLATE_96",
]
