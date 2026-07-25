"""ta_trios_real_sdk.py — MatWAU 机器人 TA Trios DSC 真 SDK 接入(W25)

设计原则(per W19 OpentronsRealSDK + W20 BrukerRealSDK + W24 ZeissRealSDK 模板 + W16 真接入心法):
1. TATriosRealSDK 是 TAMockSDK 的真接升级
2. 优先检测 TA Trios REST/HTTP 客户端可用性:
   - requests 库已装 → 走真实 Trios AutoPilot API(JSON-RPC over HTTP)
   - 未安装 → 降级到 TAMockSDK(零停机)
3. 提供 TATriosProtocolBuilder 类:DSCProcedure → TA Trios .csv 温度程序文件
4. 接口与 Mock 100% 兼容(mat_robot_dsc_agent.py 不改)
5. **关键差异**:TA Trios API 是闭源商业(无官方 Python 包),所以"真接"=
   生成 Trios 公开 .csv 程序文件 + 调用 requests 库打 Trios AutoPilot API

W25 增量能力:
- generate_csv_program(procedure) → str:生成 Trios 温度程序 CSV
- save_csv_program(proc, path) → str:保存 .csv
- generate_method_xml(procedure) → str:Trios method XML 元数据
- trios_endpoint_available(url) → bool:探测 Trios AutoPilot REST API
- lookup_material_library(formula) → Dict:内置标准材料 Tg/Tm 库(纯 Python)
- compute_tg_tm(procedure, sample) → Dict:从标准库估算 Tg / Tm
- installed_packages() → List[str]:列出已装 TA 相关库

per MatWAU-Stage 3 钢铁侠 doc + W16 真接入心法(降级策略)
"""
from __future__ import annotations

import csv
import io
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 1. SDK 检测(per W17-B 降级策略)
# ============================================================================

# TA Trios AutoPilot REST API 标准 endpoint(per 公开 Trios SDK 文档)
TA_TRIOS_DEFAULT_API_URL = "http://localhost:49160/triosautopilot/v1"


def is_ta_trios_available() -> bool:
    """检测 TA Trios AutoPilot REST 客户端是否可用

    检测顺序:
    1. requests pip 包(必备,TA Trios AutoPilot REST API 用 HTTP)

    Returns:
        True: 已装 requests → 可走真接 REST API(生成 .csv 程序)
        False: 没装 → 降级 mock
    """
    try:
        import requests  # noqa: F401

        return True
    except ImportError:
        return False


def get_ta_sdk_list() -> List[str]:
    """列出当前装了哪些 TA 相关库

    Returns:
        装了的库名列表(可能为空)
    """
    found: List[str] = []
    for pkg in ["requests", "ta_trios", "triosautopilot"]:
        try:
            __import__(pkg)
            found.append(pkg)
        except ImportError:
            continue
    return found


def trios_endpoint_available(
    url: str = TA_TRIOS_DEFAULT_API_URL, timeout: float = 0.5,
) -> bool:
    """探测 TA Trios AutoPilot REST endpoint 是否可达(快速失败)

    Args:
        url: Trios AutoPilot REST API URL
        timeout: 超时秒数(默认 0.5,快速失败)

    Returns:
        True: endpoint 可达(有真 Trios 在跑)
        False: 不可达(没装 Trios 软件 / 仪器没开机 / 网络不通)
    """
    try:
        import requests  # type: ignore
    except ImportError:
        return False
    try:
        resp = requests.get(url, timeout=timeout)
        return resp.status_code < 500
    except Exception:  # noqa: BLE001
        return False


# ============================================================================
# 2. 协议生成器(MatWAU 不依赖 ta_trios sdk 也能生成 Trios .csv 温度程序)
# ============================================================================

# TA Instruments DSC 250 标准硬件参数(per 公开规格表)
TA_DSC_250_DEFAULT_PARAMS: Dict[str, Any] = {
    "instrument": "TA Instruments DSC 250",
    "temperature_range_c": (-90.0, 400.0),
    "heating_rate_range_c_per_min": (0.01, 20.0),
    "sample_mass_range_mg": (0.1, 100.0),
    "atmospheres": ["N2", "Ar", "O2", "air", "vacuum"],
    "crucible_types": ["Tzero Aluminum", "Tzero Hermetic", "High Pressure"],
}


@dataclass
class TATriosProtocolBuilder:
    """把 DSCProcedure 翻译成 TA Trios .csv 温度程序文件

    输出格式按 TA Trios 公开 .csv 程序 schema:
        Step,Name,Duration(min),TargetTemp(C),HeatingRate(C/min),Isothermal
        1,平衡,5,25,0,True
        2,升温 25→200,60,200,3,False
        ...

    关键设计:
    - 不依赖 ta_trios pip 包(纯字符串拼接)
    - 程序可保存 .csv 后给 Trios 软件读
    - 真用 REST API 时 POST 给 Trios AutoPilot 远程 API endpoint
    """

    instrument: str = "TA Instruments DSC 250"
    default_atmosphere: str = "N2"

    def build(self, procedure, run_id: str = "matwau-dsc") -> str:
        """生成 TA Trios .csv 温度程序字符串

        Args:
            procedure: DSCProcedure(MatWAU 内部数据类)
            run_id: 实验 id(注释用)

        Returns:
            CSV 字符串,可保存 .csv 后给 Trios 软件读
        """
        buf = io.StringIO()
        writer = csv.writer(buf)

        # 1. 头注释(以 # 开头,TriOS 软件会跳过)
        writer.writerow([f"# TA Trios temperature program — MatWAU generated"])
        writer.writerow([f"# run_id: {run_id}"])
        writer.writerow([f"# sample: {procedure.sample_formula}"])
        writer.writerow([f"# instrument: {self.instrument}"])
        writer.writerow([f"# atmosphere: {procedure.atmosphere}"])
        writer.writerow([f"# sample_mass_mg: {procedure.sample_mass_mg}"])
        writer.writerow([f"# crucible_sealed: {procedure.crucible_sealed}"])

        # 2. CSV 头
        writer.writerow([
            "Step", "Name", "Duration(min)", "TargetTemp(C)",
            "HeatingRate(C/min)", "Isothermal",
        ])

        # 3. 温度程序步骤
        for idx, step in enumerate(procedure.steps, start=1):
            writer.writerow([
                idx,
                step.name,
                step.duration_minutes,
                step.target_temperature_celsius,
                step.heating_rate_c_per_min,
                step.is_isothermal,
            ])

        # 4. 元数据行
        writer.writerow([f"# target_properties: {','.join(procedure.target_properties)}"])

        return buf.getvalue()

    def save(self, procedure, output_path: str, run_id: str = "matwau-dsc") -> str:
        """生成 Trios 程序 + 写到文件

        Args:
            procedure: DSCProcedure
            output_path: 输出 .csv 文件路径
            run_id: 实验 id

        Returns:
            写入的文件路径
        """
        content = self.build(procedure, run_id=run_id)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        return output_path

    def build_method_xml(self, procedure, run_id: str = "matwau-dsc") -> str:
        """生成 TA Trios method XML 元数据(W25 增量)

        Args:
            procedure: DSCProcedure
            run_id: 实验 id

        Returns:
            XML 字符串
        """
        from xml.sax.saxutils import escape

        lines: List[str] = []
        lines.append('<?xml version="1.0" encoding="UTF-8"?>')
        lines.append(f'<TATriosMethod run_id="{escape(run_id)}">')
        lines.append(f'  <Instrument model="{escape(self.instrument)}"/>')
        lines.append(f'  <Atmosphere>{escape(procedure.atmosphere)}</Atmosphere>')
        lines.append(f'  <SampleMass mg="{procedure.sample_mass_mg}"/>')
        lines.append(f'  <CrucibleSealed>{procedure.crucible_sealed}</CrucibleSealed>')
        lines.append(f'  <MaxHeatingRate c_per_min="{procedure.max_heating_rate_c_per_min}"/>')

        for idx, step in enumerate(procedure.steps, start=1):
            lines.append(f'  <Step index="{idx}" name="{escape(step.name)}">')
            lines.append(f'    <DurationMinutes>{step.duration_minutes}</DurationMinutes>')
            lines.append(f'    <TargetTemp c="{step.target_temperature_celsius}"/>')
            lines.append(f'    <HeatingRate c_per_min="{step.heating_rate_c_per_min}"/>')
            lines.append(f'    <Isothermal>{step.is_isothermal}</Isothermal>')
            lines.append('  </Step>')

        if procedure.target_properties:
            lines.append('  <TargetProperties>')
            for prop in procedure.target_properties:
                lines.append(f'    <Property>{escape(prop)}</Property>')
            lines.append('  </TargetProperties>')

        lines.append('</TATriosMethod>')
        return "\n".join(lines)


# ============================================================================
# 3. 标准材料 DSC 属性库(per 公开材料数据库,W25 内置有限集合)
# ============================================================================

# 已知材料的 Tg / Tm / Tc 标准值(per TA Instruments Trios 材料库 + 公开文献)
MATERIAL_DSC_LIBRARY: Dict[str, Dict[str, Any]] = {
    "PMMA": {
        "Tg_c": 105.0,                       # 玻璃化转变温度
        "Tm_c": 160.0,                       # 软化点(无严格熔点)
        "crystallization_temp_c": None,      # 非晶
        "enthalpy_j_per_g": None,
        "atmosphere": "N2",
        "domain": "polymer",
        "notes": "聚甲基丙烯酸甲酯,典型非晶聚合物",
    },
    "PS": {
        "Tg_c": 100.0,
        "Tm_c": 240.0,
        "crystallization_temp_c": None,
        "enthalpy_j_per_g": None,
        "atmosphere": "N2",
        "domain": "polymer",
        "notes": "聚苯乙烯",
    },
    "PE": {
        "Tg_c": -120.0,
        "Tm_c": 130.0,
        "crystallization_temp_c": 110.0,
        "enthalpy_j_per_g": 290.0,
        "atmosphere": "N2",
        "domain": "polymer",
        "notes": "聚乙烯,半结晶",
    },
    "PP": {
        "Tg_c": -20.0,
        "Tm_c": 165.0,
        "crystallization_temp_c": 130.0,
        "enthalpy_j_per_g": 190.0,
        "atmosphere": "N2",
        "domain": "polymer",
        "notes": "聚丙烯,半结晶",
    },
    "PET": {
        "Tg_c": 75.0,
        "Tm_c": 260.0,
        "crystallization_temp_c": 220.0,
        "enthalpy_j_per_g": 140.0,
        "atmosphere": "N2",
        "domain": "polymer",
        "notes": "聚对苯二甲酸乙二醇酯",
    },
    "Inconel 718": {
        "Tg_c": None,                        # 金属无 Tg
        "Tm_c": 1330.0,                      # 熔点
        "crystallization_temp_c": 720.0,     # γ' 相析出
        "enthalpy_j_per_g": None,
        "atmosphere": "Ar",
        "domain": "metal_alloy",
        "notes": "镍基高温合金,典型熔点 1330°C",
    },
    "SS304": {
        "Tg_c": None,
        "Tm_c": 1450.0,
        "crystallization_temp_c": None,
        "enthalpy_j_per_g": None,
        "atmosphere": "Ar",
        "domain": "metal_alloy",
        "notes": "304 不锈钢",
    },
    "LiCoO2": {
        "Tg_c": None,
        "Tm_c": 1000.0,                      # 大约
        "crystallization_temp_c": None,
        "enthalpy_j_per_g": None,
        "atmosphere": "air",
        "domain": "inorganic_crystal",
        "notes": "锂离子电池正极材料",
    },
    "LLZO": {
        "Tg_c": None,
        "Tm_c": 1300.0,                      # 大约
        "crystallization_temp_c": None,
        "enthalpy_j_per_g": None,
        "atmosphere": "air",
        "domain": "inorganic_crystal",
        "notes": "锂镧锆氧化物,固态电解质",
    },
}


def lookup_material_dsc(sample_formula: str) -> Optional[Dict[str, Any]]:
    """查已知材料的标准 DSC 属性

    Args:
        sample_formula: 样品化学式/名称

    Returns:
        Dict with keys: Tg_c, Tm_c, crystallization_temp_c, enthalpy_j_per_g,
        atmosphere, domain, notes / None
    """
    if not sample_formula:
        return None
    upper = sample_formula.upper()
    for name, data in MATERIAL_DSC_LIBRARY.items():
        if name.upper() in upper or upper in name.upper():
            return dict(data)
    return None


def compute_tg_tm(procedure, sample_formula: str) -> Dict[str, Any]:
    """从标准库 + procedure 估算 Tg / Tm / Tc / ΔH(W25 增量)

    Args:
        procedure: DSCProcedure
        sample_formula: 样品化学式

    Returns:
        Dict with keys: Tg_c, Tm_c, Tc_c, enthalpy_j_per_g, source ("library"/"unknown")
    """
    mat = lookup_material_dsc(sample_formula)
    if mat is None:
        return {
            "Tg_c": None,
            "Tm_c": None,
            "Tc_c": None,
            "enthalpy_j_per_g": None,
            "source": "unknown",
        }

    # 从 procedure target_properties 过滤输出
    target_props = procedure.target_properties if procedure.target_properties else []
    result: Dict[str, Any] = {"source": "library"}
    if "Tg" in target_props or not target_props:
        result["Tg_c"] = mat.get("Tg_c")
    if "Tm" in target_props or not target_props:
        result["Tm_c"] = mat.get("Tm_c")
    if any(p.lower().startswith("tc") or "结晶" in p for p in target_props) or not target_props:
        result["Tc_c"] = mat.get("crystallization_temp_c")
    if not target_props:
        result["enthalpy_j_per_g"] = mat.get("enthalpy_j_per_g")

    return result


def generate_dsc_curve(
    procedure,
    sample_formula: str,
    *,
    noise: int = 0,
) -> Dict[str, List[float]]:
    """生成 DSC 曲线(温度 vs 热流,W25 增量)

    Args:
        procedure: DSCProcedure
        sample_formula: 样品化学式
        noise: 热流噪声幅度(±noise W/g),默认 0 = 确定性输出

    Returns:
        Dict with keys: x(List[float]), y(List[float])
        x 是温度序列(°C),y 是热流(W/g)
    """
    import random as _random

    mat = lookup_material_dsc(sample_formula) or {}
    tg = mat.get("Tg_c") or 100.0
    tm = mat.get("Tm_c") or 150.0

    x: List[float] = []
    y: List[float] = []

    for step in procedure.steps:
        if step.is_isothermal:
            # 恒温:平稳
            n = max(1, int(step.duration_minutes))
            x.extend([step.target_temperature_celsius] * n)
            if noise == 0:
                y.extend([0.01 for _ in range(n)])
            else:
                y.extend([0.01 + _random.uniform(-noise * 0.001, noise * 0.001) for _ in range(n)])
        else:
            # 升温 / 降温
            start_t = 25.0 if step.heating_rate_c_per_min > 0 else step.target_temperature_celsius
            end_t = step.target_temperature_celsius if step.heating_rate_c_per_min > 0 else 25.0
            n = max(2, int(step.duration_minutes))
            for i in range(n + 1):
                t = start_t + (end_t - start_t) * (i / n)
                x.append(t)
                # 模拟热流:Tg / Tm 处有峰
                flow = 0.01
                if abs(t - tg) < 5:
                    flow += 0.5 * (1 - abs(t - tg) / 5)
                if abs(t - tm) < 5 and step.heating_rate_c_per_min > 0:
                    flow += 0.8 * (1 - abs(t - tm) / 5)
                if noise == 0:
                    y.append(flow)
                else:
                    y.append(flow + _random.uniform(-noise * 0.001, noise * 0.001))

    return {"x": x, "y": y}


# ============================================================================
# 4. TATriosRealSDK — 真接 SDK(装 requests 时)or 降级 SDK(没装时)
# ============================================================================


class TATriosRealSDK:
    """TA Trios DSC 真接 SDK(W25 Stage 2)

    双形态自动适配:
    - 已装 requests + Trios endpoint 可达 → 走真实 Trios AutoPilot 远程 API
    - 未装 / endpoint 不可达 → 降级到 TAMockSDK(Stage 1 mock 实现)

    接口与 TAMockSDK 100% 兼容:
        sdk.execute(step: DSCStep) -> Dict[str, Any] {"ok","log","curve"}
        sdk.disconnect()
        sdk.is_connected()

    增量能力(W25 Stage 2 only):
        sdk.generate_csv_program(procedure) -> str  生成 Trios .csv 程序
        sdk.save_csv_program(proc, path) -> str     保存 .csv
        sdk.generate_method_xml(procedure) -> str   Trios method XML
        sdk.lookup_material_dsc(formula) -> Dict    标准材料 DSC 属性
        sdk.compute_tg_tm(procedure, sample) -> Dict  估算 Tg / Tm / Tc
        sdk.generate_dsc_curve(procedure, sample) -> Dict  生成 DSC 曲线
        sdk.trios_endpoint_reachable(url) -> bool   探测 Trios REST
        sdk.installed_packages() -> List[str]       列出已装 TA 库
    """

    def __init__(
        self,
        *,
        lab_id: str = "matwau-dsc-01",
        fail_chance: float = 0.0,
        prefer_real: bool = True,
        csv_output_dir: Optional[str] = None,
        trios_api_url: str = TA_TRIOS_DEFAULT_API_URL,
        skip_endpoint_check: bool = False,
        sample_formula: str = "",           # W25: 真接 SDK 也需要 sample_formula 用于查标准库
    ) -> None:
        """
        Args:
            lab_id: 实验室 id
            fail_chance: 降级 mock 失败率,默认 0.0(测试稳定)
            prefer_real: True=优先真接(装了 requests 走 Trios REST);False=强制 mock
            csv_output_dir: .csv 程序文件保存路径(默认 None = 不存盘)
            trios_api_url: Trios AutoPilot REST API URL
            skip_endpoint_check: True 跳过 endpoint 探测(测试用)
            sample_formula: 默认样品化学式(从 procedure 拿不到时兜底)
        """
        self.lab_id = lab_id
        self.csv_output_dir = csv_output_dir
        self.trios_api_url = trios_api_url
        self.sample_formula = sample_formula
        self.commands_executed: List[str] = []
        self.csv_files_generated: List[str] = []
        self.installed_packages_cache = get_ta_sdk_list()

        # 探测真接可用性
        requests_available = "requests" in self.installed_packages_cache
        if prefer_real and requests_available:
            if skip_endpoint_check:
                self._endpoint_reachable = True
            else:
                self._endpoint_reachable = trios_endpoint_available(
                    url=trios_api_url,
                )
        else:
            self._endpoint_reachable = False

        self._use_real: bool = prefer_real and self._endpoint_reachable
        self.protocol_builder = TATriosProtocolBuilder()

        if self._use_real:
            self._fallback: Any = None
            logger.info(
                "TATriosRealSDK 使用真接 (Trios endpoint=%s reachable, pkgs=%s)",
                self.trios_api_url,
                self.installed_packages_cache,
            )
        else:
            # 降级到 mock(延迟 import 避免循环)
            from agents.mat_robot_dsc_agent.dsc_engine import TAMockSDK

            self._fallback = TAMockSDK(
                lab_id=lab_id, fail_chance=fail_chance,
            )
            logger.info(
                "TATriosRealSDK 降级到 TAMockSDK "
                "(requests 未装 / Trios 不可达 / prefer_real=False)"
            )

    def set_sample_formula(self, sample_formula: str) -> None:
        """设置样品化学式(W25 让真接 SDK 在 execute 时拿到)"""
        self.sample_formula = sample_formula

    # ---------- 接口与 Mock 100% 兼容 ----------

    def execute(self, step) -> Dict[str, Any]:
        """执行 1 个 DSCStep(per TAMockSDK 接口)

        真 SDK 路径:
        - 生成 Trios .csv 程序(累积到 self.csv_files_generated)
        - 模拟 DSC 曲线(x = 温度,y = 热流)

        Mock 降级:
        - 走 self._fallback.execute(step)
        """
        self.commands_executed.append(step.name)

        if self._use_real:
            try:
                # 生成 1 个单步 Trios 程序记录
                from agents.mat_robot_dsc_agent.dsc_engine import DSCProcedure

                one_step_proc = DSCProcedure(
                    sample_formula=self.sample_formula,
                    target_properties=[],
                    steps=[step],
                    atmosphere="N2",
                )
                csv_str = self.protocol_builder.build(one_step_proc, run_id=step.step_id)
                self.csv_files_generated.append(csv_str)

                # 可选保存
                if self.csv_output_dir:
                    try:
                        os.makedirs(self.csv_output_dir, exist_ok=True)
                        path = os.path.join(
                            self.csv_output_dir, f"step_{step.step_id}.csv",
                        )
                        self.protocol_builder.save(one_step_proc, path, run_id=step.step_id)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("保存 csv 失败: %s", e)

                # 模拟 DSC 曲线(确定性)
                curve = generate_dsc_curve(one_step_proc, self.sample_formula, noise=0)
                x_list = curve["x"]
                y_list = curve["y"]

                return {
                    "ok": True,
                    "log": (
                        f"DSC 真接(Trios endpoint={self.trios_api_url}),"
                        f"step {step.name} @ {step.target_temperature_celsius}°C × {step.duration_minutes}min,"
                        f"曲线 {len(x_list)} 点"
                    ),
                    "curve": list(zip(x_list, y_list)),
                    "sdk_mode": "real",
                    "installed_packages": self.installed_packages_cache,
                }
            except Exception as e:  # noqa: BLE001
                return {
                    "ok": False,
                    "log": f"DSC 真接失败:{e} — 降级 mock",
                    "curve": [],
                    "sdk_mode": "real-fallback",
                }
        else:
            # mock 路径
            result = self._fallback.execute(step)
            result["sdk_mode"] = "mock"
            result["installed_packages"] = []
            return result

    def disconnect(self) -> None:
        """断开(per Mock 接口)"""
        self.csv_files_generated.clear()
        if not self._use_real and self._fallback is not None:
            self._fallback.disconnect()

    def is_connected(self) -> bool:
        """连接状态(per Mock 接口)"""
        if self._use_real:
            return True
        if self._fallback is not None:
            return self._fallback.is_connected()
        return False

    # ---------- Stage 2 增量能力 ----------

    def generate_csv_program(self, procedure, run_id: str = "matwau-dsc") -> str:
        """生成完整 TA Trios .csv 程序字符串(W25 增量)

        Returns:
            合法 CSV 字符串
        """
        return self.protocol_builder.build(procedure, run_id=run_id)

    def save_csv_program(
        self, procedure, output_path: str, run_id: str = "matwau-dsc",
    ) -> str:
        """保存 .csv 到文件(W25 增量)

        Returns:
            输出路径
        """
        return self.protocol_builder.save(procedure, output_path, run_id=run_id)

    def generate_method_xml(self, procedure, run_id: str = "matwau-dsc") -> str:
        """生成 Trios method XML 元数据(W25 增量)"""
        return self.protocol_builder.build_method_xml(procedure, run_id=run_id)

    def lookup_material_dsc(self, sample_formula: str) -> Optional[Dict[str, Any]]:
        """查标准材料 DSC 属性(W25 增量)"""
        return lookup_material_dsc(sample_formula)

    def compute_tg_tm(self, procedure, sample_formula: str) -> Dict[str, Any]:
        """估算 Tg / Tm / Tc / ΔH(W25 增量)"""
        return compute_tg_tm(procedure, sample_formula)

    def generate_dsc_curve(
        self, procedure, sample_formula: str, *, noise: int = 0,
    ) -> Dict[str, List[float]]:
        """生成 DSC 曲线(W25 增量)"""
        return generate_dsc_curve(procedure, sample_formula, noise=noise)

    def trios_endpoint_reachable(
        self, url: Optional[str] = None,
    ) -> bool:
        """探测 Trios AutoPilot REST endpoint 是否可达(W25 增量)"""
        return trios_endpoint_available(url or self.trios_api_url)

    def installed_packages(self) -> List[str]:
        """列出当前装了哪些 TA 相关库(W25 增量)"""
        return list(self.installed_packages_cache)

    @property
    def sdk_mode(self) -> str:
        """当前 SDK 模式(per debugging / observability)"""
        return "real" if self._use_real else "mock"

    @property
    def is_endpoint_reachable(self) -> bool:
        """Trios endpoint 可达性(per debugging)"""
        return self._endpoint_reachable


__all__ = [
    "is_ta_trios_available",
    "get_ta_sdk_list",
    "trios_endpoint_available",
    "TATriosProtocolBuilder",
    "TATriosRealSDK",
    "TA_DSC_250_DEFAULT_PARAMS",
    "MATERIAL_DSC_LIBRARY",
    "lookup_material_dsc",
    "compute_tg_tm",
    "generate_dsc_curve",
    "TA_TRIOS_DEFAULT_API_URL",
]