"""vasp_slurm.py — VASP 输入文件生成 + Slurm 作业调度 mock

Stage 1 / Phase 1:本地 mock,不需要真超算环境
Stage 2(WAU v1.0.0 GA + 服务器 GPU 后)切真 VASP + 真 Slurm

VASP 4 件套(per 开发计划 §5.4):
1. INCAR — 计算参数(ENCUT / EDIFF / IBRION / ISIF / NSW)
2. KPOINTS — K 点网格(Monkhorst-Pack / Auto)
3. POSCAR — 结构文件(晶格 + 原子坐标)
4. POTCAR — 赝势文件(Stage 1 mock,Stage 2 接 Materials Project API)

Slurm mock:
- generate_job_id() — 返回 job-<hash> 格式
- submit_job() — mock 提交,80%+ 成功
- estimate_cost() — per-node × walltime × ¥10/node/h
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ============================================================================
# 数据类
# ============================================================================


@dataclass
class HPCJobResult:
    """1 个 HPC job 的结果(per act() 输出)"""

    job_id: str
    formula: str
    status: str  # "submitted" / "completed" / "failed" / "blocked"
    estimated_cost: float  # ¥
    walltime_hours: float
    n_nodes: int
    n_cores_per_node: int
    vasp_inputs: Dict[str, str] = field(default_factory=dict)  # INCAR/KPOINTS/POSCAR/POTCAR
    slurm_script: str = ""  # Slurm 提交脚本
    cluster: str = "mock-cluster"  # Stage 1 mock / Stage 2 真实集群


@dataclass
class HPCRuntimeConstraints:
    """mat-hpc 任务约束(从用户 query 解析)"""

    formula: str = ""
    n_candidates: int = 1
    calculation_type: str = "relax"  # "relax" / "static" / "dos" / "band"
    budget: Optional[float] = None


# ============================================================================
# 元素 → 赝势名(Stage 1 mock,Stage 2 接 Materials Project API)
# ============================================================================

ELEMENT_POTCAR = {
    "Li": "Li_sv", "Na": "Na_pv", "Mg": "Mg_pv", "K": "K_sv", "Ca": "Ca_sv",
    "Al": "Al", "Ti": "Ti_sv", "V": "V_sv", "Cr": "Cr_pv", "Mn": "Mn_pv",
    "Fe": "Fe_pv", "Co": "Co", "Ni": "Ni_pv", "Cu": "Cu_pv", "Zn": "Zn",
    "Ga": "Ga_d", "Zr": "Zr_sv", "Nb": "Nb_sv", "Mo": "Mo_pv", "Ag": "Ag",
    "Sn": "Sn_d", "Sb": "Sb", "La": "La", "Ce": "Ce", "Nd": "Nd_3",
    "Sm": "Sm_3", "Y": "Y_sv", "W": "W_pv", "Pt": "Pt", "Au": "Au",
    "Si": "Si", "P": "P", "S": "S", "Cl": "Cl", "Br": "Br", "I": "I",
    "O": "O", "N": "N", "C": "C", "H": "H", "B": "B", "F": "F",
}


# ============================================================================
# 元素提取
# ============================================================================


def _extract_elements(formula: str) -> List[str]:
    """从化学式提取元素列表(去重保序)"""
    tokens = re.findall(r"([A-Z][a-z]?)", formula)
    seen = set()
    elements = []
    for tok in tokens:
        if tok not in seen:
            seen.add(tok)
            elements.append(tok)
    return elements


def _count_atoms(formula: str) -> int:
    """估算原子数(简化:解析化学式下标)

    例:'Li2O' → 3,'LiCoO2' → 4,'Li20Co10O30' → 60
    """
    total = 0
    for match in re.finditer(r"([A-Z][a-z]?)(\d*)", formula):
        elem = match.group(1)
        count_str = match.group(2)
        count = int(count_str) if count_str else 1
        total += count
    return total


# ============================================================================
# VASP 输入文件生成
# ============================================================================


def generate_incar(formula: str, calc_type: str = "relax") -> str:
    """生成 INCAR 文件

    Stage 1 标准参数(per VASP wiki):
    - ENCUT = 520 eV(PBE 赝势推荐)
    - EDIFF = 1e-5(能量收敛)
    - IBRION = 2(共轭梯度,relax)
    - ISIF = 3(relax cell + ions)
    - NSW = 100(最大离子步)
    """
    incar = f"""SYSTEM = {formula}
ENCUT = 520
EDIFF = 1E-05
EDIFFG = -0.02
IBRION = 2
ISIF = 3
ISMEAR = 0
SIGMA = 0.05
NSW = 100
LREAL = Auto
LWAVE = .FALSE.
LCHARG = .FALSE.
"""
    if calc_type == "static":
        incar += "IBRION = -1\nNSW = 0\n"
    elif calc_type == "dos":
        incar += "ICHARG = 11\nNEDOS = 3001\n"
    elif calc_type == "band":
        incar += "ICHARG = 11\nLORBIT = 11\n"

    return incar


def generate_kpoints(formula: str, calc_type: str = "relax") -> str:
    """生成 KPOINTS 文件(Monkhorst-Pack 自动网格)

    Stage 1 简化:用密度 k = 0.04 1/Å(per VASP 标准)
    Stage 2 接 Materials Project API 查推荐网格
    """
    # 默认 K 点密度
    n_kpoints = 6  # 6x6x6 网格
    return f"""KPOINTS
0
Monkhorst-Pack
{n_kpoints} {n_kpoints} {n_kpoints}
0 0 0
"""


def generate_poscar(formula: str, cif: str = "") -> str:
    """生成 POSCAR 文件

    Stage 1 mock:从 cif 解析或生成假结构
    格式:comment + 缩放 + 3 晶格矢量 + 元素 + 原子数 + 坐标
    """
    elements = _extract_elements(formula)
    if not elements:
        elements = ["X"]

    # Stage 1 简化:假设每元素 1 个原子(per formula unit)
    atom_counts = []
    for elem in elements:
        # 简单算法:每个元素在 formula 出现 1 次
        atom_counts.append(1)

    # 假晶格(立方,a=4.5 Å,Stage 1 mock)
    lattice_scale = 4.5

    poscar = f"""{formula}
   {lattice_scale}
     1.000000000   0.000000000   0.000000000
     0.000000000   1.000000000   0.000000000
     0.000000000   0.000000000   1.000000000
   {' '.join(elements)}
   {' '.join(str(c) for c in atom_counts)}
Cartesian
"""
    # 加原子坐标(简化:均匀分布)
    for i, (elem, count) in enumerate(zip(elements, atom_counts)):
        for j in range(count):
            x = 0.1 * (i + 1) + 0.05 * j
            y = 0.1 * (i + 1) + 0.05 * j
            z = 0.1 * (i + 1) + 0.05 * j
            poscar += f"   {x:.6f}   {y:.6f}   {z:.6f}\n"

    return poscar


def generate_potcar(formula: str) -> str:
    """生成 POTCAR.spec(Stage 1 mock,Stage 2 接 VASP 官方 POTCAR)"""
    elements = _extract_elements(formula)
    potcar_spec_lines = []
    for elem in elements:
        potcar_name = ELEMENT_POTCAR.get(elem, elem)
        potcar_spec_lines.append(f"{potcar_name}")

    return "\n".join(potcar_spec_lines)


def generate_vasp_inputs(formula: str, cif: str = "", calc_type: str = "relax") -> Dict[str, str]:
    """生成 VASP 4 件套"""
    return {
        "INCAR": generate_incar(formula, calc_type),
        "KPOINTS": generate_kpoints(formula, calc_type),
        "POSCAR": generate_poscar(formula, cif),
        "POTCAR.spec": generate_potcar(formula),
    }


# ============================================================================
# Slurm 脚本生成
# ============================================================================


def generate_slurm_script(
    formula: str,
    n_nodes: int,
    n_cores_per_node: int,
    walltime_hours: float,
    job_name: str = "vasp_job",
) -> str:
    """生成 Slurm 提交脚本(per Slurm 标准)"""
    # 格式化 walltime 为 HH:MM:00
    walltime_str = f"{int(walltime_hours):02d}:{int((walltime_hours % 1) * 60):02d}:00"

    return f"""#!/bin/bash
#SBATCH --job-name={job_name}_{formula}
#SBATCH --nodes={n_nodes}
#SBATCH --ntasks-per-node={n_cores_per_node}
#SBATCH --time={walltime_str}
#SBATCH --partition=normal
#SBATCH --output=vasp_{formula}.out
#SBATCH --error=vasp_{formula}.err

# Stage 1 mock / Stage 2 real VASP
module load VASP/6.3.0

# Run VASP
srun vasp_std > vasp_{formula}.log 2>&1

echo "Job finished at $(date)"
"""


# ============================================================================
# HPC 资源估算
# ============================================================================


def estimate_resources(
    formula: str,
    calc_type: str = "relax",
) -> Dict[str, float]:
    """估算 HPC 资源(nodes / cores / walltime)

    简化模型(per VASP 经验):
    - 小体系(< 10 原子):1 node × 24 cores × 1-2 hours
    - 中体系(10-50 原子):1 node × 48 cores × 2-6 hours
    - 大体系(50-200 原子):2-4 nodes × 48 cores × 6-24 hours
    - 超大(> 200 原子):4-16 nodes × 48 cores × 24+ hours

    Stage 2 升级:接 VASP 性能模型(per Materials Project 标准)
    """
    n_atoms = _count_atoms(formula)

    # 按原子数分桶
    if n_atoms < 10:
        n_nodes = 1
        cores_per_node = 24
        base_walltime = 1.0
        per_atom_factor = 0.1
    elif n_atoms < 50:
        n_nodes = 1
        cores_per_node = 48
        base_walltime = 2.0
        per_atom_factor = 0.15
    elif n_atoms < 200:
        n_nodes = 2
        cores_per_node = 48
        base_walltime = 6.0
        per_atom_factor = 0.2
    else:
        n_nodes = 4
        cores_per_node = 48
        base_walltime = 24.0
        per_atom_factor = 0.3

    # calc_type 调整
    type_factor = {
        "relax": 1.0,
        "static": 0.5,
        "dos": 2.0,
        "band": 3.0,
    }.get(calc_type, 1.0)

    walltime = base_walltime + n_atoms * per_atom_factor * type_factor

    return {
        "n_nodes": float(n_nodes),
        "n_cores_per_node": float(cores_per_node),
        "walltime_hours": round(walltime, 2),
        "n_atoms": float(n_atoms),
    }


def estimate_cost(
    n_nodes: int,
    walltime_hours: float,
    cost_per_node_hour: float = 10.0,
    cores_per_node: int = 24,
) -> float:
    """估算 HPC 成本 ¥

    公式:nodes × walltime_hours × cost_per_node_hour × cores_factor

    简化:nodes × walltime × ¥10/node/h(不含 core 因子,Stage 2 接真实计费)
    """
    cost = n_nodes * walltime_hours * cost_per_node_hour
    return round(cost, 2)


# ============================================================================
# Slurm 作业提交(mock)
# ============================================================================


def generate_job_id(formula: str, seed: int = 0) -> str:
    """生成 Slurm job_id 格式:job-<10 字符 hash>"""
    h = hashlib.md5(f"{formula}-{seed}".encode()).hexdigest()[:10]
    return f"job-{h}"


def submit_job(
    formula: str,
    calc_type: str = "relax",
    cost_per_node_hour: float = 10.0,
    seed: int = 0,
    cif: str = "",
) -> HPCJobResult:
    """Slurm mock:提交 1 个 HPC job

    Stage 1 mock 行为:
    - 80% 成功(submitted)
    - 15% 完成(completed — Stage 1 假装瞬时完成)
    - 5% 失败(failed — Stage 1 模拟偶发错误)

    Stage 2 切真 Slurm + VASP,返回真实 job_id + 真实 status
    """
    rng = random.Random(seed + hash(formula))

    # 估算资源
    resources = estimate_resources(formula, calc_type)
    n_nodes = int(resources["n_nodes"])
    cores_per_node = int(resources["n_cores_per_node"])
    walltime_hours = resources["walltime_hours"]

    # 估算成本
    cost = estimate_cost(n_nodes, walltime_hours, cost_per_node_hour, cores_per_node)

    # 生成 VASP 输入
    vasp_inputs = generate_vasp_inputs(formula, cif, calc_type)

    # 生成 Slurm 脚本
    slurm_script = generate_slurm_script(
        formula=formula,
        n_nodes=n_nodes,
        n_cores_per_node=cores_per_node,
        walltime_hours=walltime_hours,
    )

    # 决定 status(Stage 1 mock)
    rand_val = rng.random()
    if rand_val < 0.80:
        status = "submitted"
    elif rand_val < 0.95:
        status = "completed"
    else:
        status = "failed"

    return HPCJobResult(
        job_id=generate_job_id(formula, seed),
        formula=formula,
        status=status,
        estimated_cost=cost,
        walltime_hours=walltime_hours,
        n_nodes=n_nodes,
        n_cores_per_node=cores_per_node,
        vasp_inputs=vasp_inputs,
        slurm_script=slurm_script,
        cluster="mock-cluster",
    )


def submit_batch(
    candidates: List,
    calc_type: str = "relax",
    cost_per_node_hour: float = 10.0,
    cost_threshold: float = 1000.0,
    seed_base: int = 0,
) -> List[HPCJobResult]:
    """批量提交 HPC job

    Args:
        candidates: List[SimCandidate] / List[GenCandidate] / List[dict]
        calc_type: VASP 计算类型
        cost_per_node_hour: per-node ¥/h
        cost_threshold: 单 job cost 阈值,超过 → status=blocked(需 supervisor 审批)
        seed_base: 起始随机种子

    Returns:
        List[HPCJobResult]
    """
    results = []
    for i, cand in enumerate(candidates):
        # 兼容 dataclass 和 dict
        if hasattr(cand, "formula"):
            formula = cand.formula
            cif = getattr(cand, "cif", "")
        elif isinstance(cand, dict):
            formula = cand.get("formula", "X")
            cif = cand.get("cif", "")
        else:
            formula = f"X{i}"
            cif = ""

        job = submit_job(
            formula=formula,
            calc_type=calc_type,
            cost_per_node_hour=cost_per_node_hour,
            seed=seed_base + i,
            cif=cif,
        )

        # 高 cost 拦截(per dev plan §5.4:> ¥1000 需 supervisor 审批)
        if job.estimated_cost > cost_threshold:
            job.status = "blocked"
            results.append(job)
        else:
            results.append(job)

    return results


def parse_constraints(user_message: str) -> HPCRuntimeConstraints:
    """从用户消息解析约束(Stage 1 规则解析)

    Stage 2 升级:走 wau-python-sdk 调 LLM
    """
    msg = user_message.lower()

    # 提取公式
    formula_match = re.search(r"\b([A-Z][a-z]?\d*[A-Z][a-z]?\d*)\b", user_message)
    formula = formula_match.group(1) if formula_match else ""

    # 计算类型
    calc_type = "relax"
    if "static" in msg or "静态" in user_message:
        calc_type = "static"
    elif "dos" in msg or "态密度" in user_message:
        calc_type = "dos"
    elif "band" in msg or "能带" in user_message:
        calc_type = "band"

    return HPCRuntimeConstraints(
        formula=formula,
        calculation_type=calc_type,
    )


def stats(results: List[HPCJobResult]) -> Dict[str, int]:
    """统计 HPC 作业"""
    return {
        "total": len(results),
        "submitted": sum(1 for r in results if r.status == "submitted"),
        "completed": sum(1 for r in results if r.status == "completed"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "blocked": sum(1 for r in results if r.status == "blocked"),
        "total_cost": round(sum(r.estimated_cost for r in results), 2),
        "total_walltime": round(sum(r.walltime_hours for r in results), 2),
    }


__all__ = [
    "HPCJobResult",
    "HPCRuntimeConstraints",
    "generate_incar",
    "generate_kpoints",
    "generate_poscar",
    "generate_potcar",
    "generate_vasp_inputs",
    "generate_slurm_script",
    "estimate_resources",
    "estimate_cost",
    "generate_job_id",
    "submit_job",
    "submit_batch",
    "parse_constraints",
    "stats",
    "ELEMENT_POTCAR",
]