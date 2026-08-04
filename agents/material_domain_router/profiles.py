"""profiles.py — 3 个材料域 profile 定义(W15)

每个 profile 含 7 个核心字段:
- elements: 元素池(per 域)
- material_aliases: 材料别名(per 域高频词)
- property_keywords: 属性词(per 域关注指标)
- domain_keywords: 应用领域词(per 域用途)
- gen_backend: 生成模型 backend(W2 接入)
- sim_backend: MLIP / MD backend(W2 接入)
- hpc_engine: HPC 引擎(W2 接入)
- lit_backend: 文献库 backend(W14 mock)
- unit_cost: 单价表(per agent / per unit)

Stage 1: 纯 dict 查表
Stage 2: wau-domain-registry SDK 注入 + 真实 backend 替换
"""
from __future__ import annotations

from typing import Any

# ============================================================================
# 3 个域 profile
# ============================================================================


INORGANIC_CRYSTAL_PROFILE: dict[str, Any] = {
    "name": "inorganic_crystal",
    "display_name_zh": "无机晶体",
    "description": "无机晶体材料(锂电池正极 / 固态电解质 / 催化剂 / 太阳能电池 / 超导 / 热电 / 永磁 / 半导体 / 储氢 ...)",
    "elements": [
        "Li", "Na", "K", "Mg", "Ca", "Sr", "Ba",
        "Al", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
        "Zr", "Nb", "Mo", "Ru", "Rh", "Pd", "Ag", "Cd", "Sn", "Sb",
        "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Pb", "Bi",
        "Sc", "Y", "La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb",
        "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
        "Si", "Ge", "As", "Se", "Te",
        "O", "S", "F", "Cl", "Br", "I", "N", "P", "C", "B", "H",
    ],
    "material_aliases": [
        "LLZO", "LGPS", "LATP", "LAGP", "NASICON",
        "LFP", "LiFePO4",
        "NMC", "NMC111", "NMC622", "NMC811",
        "LCO", "LiCoO2",
        "LMO", "LiMn2O4",
        "NCA", "LiNiCoAlO2",
        "PZT", "BaTiO3", "SrTiO3",
        "PVDF",  # 既是高分子也是无机压电材料
    ],
    "property_keywords": [
        "电导率", "ionic conductivity",
        "晶格常数", "lattice parameter",
        "形成能", "formation energy",
        "带隙", "band gap",
        "能量密度", "energy density",
        "容量", "capacity",
        "电压", "voltage",
        "稳定性", "stability",
        "循环寿命", "cycle life",
        "超导转变温度", "Tc",
        "热电优值", "ZT",
        "居里温度", "Curie temperature",
        "介电常数", "dielectric constant",
    ],
    "domain_keywords": [
        "锂电池", "lithium battery",
        "固态电池", "solid-state battery",
        "燃料电池", "fuel cell",
        "太阳能电池", "solar cell",
        "催化剂", "catalyst",
        "析氢", "HER",
        "析氧", "OER",
        "超导", "superconductor",
        "热电", "thermoelectric",
        "永磁", "permanent magnet",
        "半导体", "semiconductor",
        "储氢", "hydrogen storage",
    ],
    "gen_backend": "mattergen",          # MatterGen 扩散模型
    "sim_backend": "chgnet",             # CHGNet MLIP
    "hpc_engine": "vasp",                # VASP DFT
    "lit_backend": "mock_materials",     # W14 mock,Stage 2 arXiv + Materials Project
    "exp_methods": [
        "固相法", "sol-gel", "水热合成", "hydrothermal",
        "共沉淀", "高温烧结", "sintering",
        "XRD", "SEM", "TEM", "XPS",
        "充放电测试", "循环伏安", "CV",
        "EIS", "电化学阻抗",
    ],
    "unit_cost": {
        # / 候选 / job / 配方 / 次
        "mat-gen-agent": 0.06,            # ¥/候选(MatterGen + LLM)
        "mat-sim-agent": 0.5,             # ¥/候选(CHGNet MLIP 推理)
        "mat-hpc-agent": 100.0,           # ¥/job(VASP)
        "mat-exp-agent": 10.0,            # ¥/配方(实验台时 + 试剂)
        "mat-critic-agent": 0.05,         # ¥/次(规则引擎)
        "mat-bayesian-agent": 0.02,       # ¥/次(NumPy)
        "mat-lit-agent": 0.1,             # ¥/次(mock 数据库)
        "mat-intent-agent": 0.01,         # ¥/次(简单分类)
        "mat-cost-agent": 0.001,          # ¥/次(本地计算)
        "mat-data-lineage-agent": 0.001,  # ¥/次(本地存储)
    },
}


POLYMER_PROFILE: dict[str, Any] = {
    "name": "polymer",
    "display_name_zh": "高分子聚合物",
    "description": "高分子聚合物(导电聚合物 / 介电聚合物 / 水凝胶 / 弹性体 / 热塑性 / 热固性 / 3D 打印耗材 ...)",
    "elements": [
        # 高分子主链元素(C/H/O/N 为主)
        "C", "H", "O", "N", "S", "P", "F", "Cl", "Si",
        # 常见掺杂元素
        "Li", "Na", "Mg", "Al", "Ti", "Zn",
        # 卤素(阻燃)
        "Br", "I",
    ],
    "material_aliases": [
        "PMMA", "聚甲基丙烯酸甲酯",
        "PDMS", "聚二甲基硅氧烷",
        "PEEK", "聚醚醚酮",
        "PI", "聚酰亚胺", "polyimide",
        "PEG", "聚乙二醇",
        "PAN", "聚丙烯腈",
        "PVDF", "PVDF-HFP",
        "PE", "聚乙烯",
        "PP", "聚丙烯",
        "PS", "聚苯乙烯",
        "PVC", "聚氯乙烯",
        "PLA", "聚乳酸",
        "PHB",
        "PEDOT", "PSS", "PEDOT:PSS",
        "PANI", "聚苯胺",
        "PPy", "聚吡咯",
        "PVA", "聚乙烯醇",
        "水凝胶", "hydrogel",
        "环氧树脂", "epoxy",
        "酚醛", "phenolic",
        "硅橡胶", "silicone rubber",
    ],
    "property_keywords": [
        "玻璃化转变温度", "Tg",
        "熔体流动指数", "MFI",
        "拉伸强度", "tensile strength",
        "杨氏模量", "Young's modulus",
        "断裂伸长率", "elongation at break",
        "介电常数", "dielectric constant",
        "介电损耗", "dielectric loss",
        "导电率", "electrical conductivity",
        "聚合度", "degree of polymerization",
        "分子量", "molecular weight",
        "分子量分布", "MWD", "PDI",
        "Mark-Houwink", "Fox-Flory",
        "储能模量", "storage modulus",
        "损耗模量", "loss modulus",
        "tan δ", "损耗因子",
        "热分解温度", "Td",
        "熔点", "Tm", "melting point",
        "结晶度", "crystallinity",
        "交联密度", "crosslink density",
        "吸水率", "water absorption",
        "透光率", "transmittance",
        "雾度", "haze",
        "氧气透过率", "OTR",
        "水蒸气透过率", "WVTR",
    ],
    "domain_keywords": [
        "柔性电子", "flexible electronics",
        "可穿戴", "wearable",
        "生物医用", "biomedical",
        "药物载体", "drug delivery",
        "组织工程", "tissue engineering",
        "3D 打印", "3D printing",
        "FDM", "SLA",
        "静电纺丝", "electrospinning",
        "包装", "packaging",
        "阻燃", "flame retardant",
        "导电胶", "conductive adhesive",
        "介电储能", "dielectric energy storage",
        "形状记忆", "shape memory",
        "自愈合", "self-healing",
        "光刻胶", "photoresist",
        "OLED", "有机太阳能",
    ],
    "gen_backend": "polymer_rnn",        # 高分子序列生成
    "sim_backend": "ani1x",              # ani1x MLIP(可处理有机分子)
    "hpc_engine": "lammps",              # LAMMPS 分子动力学
    "lit_backend": "mock_polymers",      # W15 mock,Stage 2 arXiv + Polymer Property Predictor DB
    "exp_methods": [
        "自由基聚合", "free radical polymerization",
        "逐步聚合", "step-growth polymerization",
        "缩聚", "condensation polymerization",
        "加聚", "addition polymerization",
        "RAFT", "ATRP", "活性聚合",
        "GPC", "凝胶渗透色谱",
        "DSC", "差示扫描量热",
        "TGA", "热重分析",
        "DMA", "动态力学分析",
        "流变", "rheology",
        "注塑", "injection molding",
        "挤出", "extrusion",
        "吹塑", "blow molding",
        "静电纺丝", "electrospinning",
        "溶液浇铸", "solution casting",
        "旋涂", "spin coating",
    ],
    "unit_cost": {
        "mat-gen-agent": 0.02,            # ¥/分子链(纯 RNN,轻量)
        "mat-sim-agent": 0.2,             # ¥/候选(ani1x 比 CHGNet 便宜)
        "mat-hpc-agent": 30.0,            # ¥/job(LAMMPS 比 VASP 便宜)
        "mat-exp-agent": 5.0,             # ¥/样品(注塑 / 静电纺丝 / DSC)
        "mat-critic-agent": 0.05,
        "mat-bayesian-agent": 0.02,
        "mat-lit-agent": 0.1,
        "mat-intent-agent": 0.01,
        "mat-cost-agent": 0.001,
        "mat-data-lineage-agent": 0.001,
    },
}


NANO_PROFILE: dict[str, Any] = {
    "name": "nano",
    "display_name_zh": "纳米材料",
    "description": "纳米材料(量子点 / 纳米线 / 2D 材料(石墨烯 / MoS₂ / TMDC)/ 介孔材料 / 纳米晶 / 纳米团簇 / 异质结 ...)",
    "elements": [
        # 2D 材料主元素
        "C", "Mo", "S", "Se", "Te", "W",
        # 量子点常见元素
        "Cd", "Pb", "Se", "Te", "Zn", "S", "In", "As", "P",
        # 金属纳米
        "Au", "Ag", "Cu", "Pt", "Pd", "Ru",
        # 氧化物
        "O", "Ti", "Fe", "Si", "Al", "Zr", "Ce",
        # 衬底元素
        "Si", "Ge", "Ga", "As",
        # 配体元素
        "N", "P", "Cl", "Br", "I", "H",
    ],
    "material_aliases": [
        # 量子点
        "CdSe", "CdTe", "PbS", "PbSe", "ZnS", "ZnSe", "InP", "InAs",
        "CsPbI3", "CsPbBr3", "CsPbCl3",  # 钙钛矿 QD
        # 2D 材料
        "石墨烯", "graphene", "GO", "rGO",
        "MoS2", "MoS_2", "二硫化钼",
        "WS2", "WSe2", "MoSe2", "TMDC",
        "hBN", "六方氮化硼",
        "MXene", "Ti3C2",
        "黑磷", "black phosphorus", "BP",
        "硅烯", "silicene", "锗烯", "germanene",
        # 纳米结构
        "纳米线", "nanowire", "NW",
        "纳米管", "CNT", "carbon nanotube", "SWCNT", "MWCNT",
        "纳米片", "nanosheet",
        "纳米团簇", "nanocluster",
        "纳米晶", "nanocrystal",
        # 介孔 / 多孔
        "MCM-41", "SBA-15", "介孔二氧化硅",
        "MOF", "ZIF-8", "HKUST-1",
        "COF",
        # 异质结
        "异质结", "heterojunction",
        "vdW", "范德华异质结",
    ],
    "property_keywords": [
        "比表面积", "BET", "specific surface area",
        "量子限域", "quantum confinement",
        "Brus 方程", "Brus equation",
        "表面等离子体共振", "LSPR",
        "局域表面等离子体",
        "表面态密度", "surface state density",
        "缺陷态", "defect state",
        "激子结合能", "exciton binding energy",
        "荧光量子产率", "PLQY", "QY",
        "荧光寿命", "PL lifetime",
        "发射波长", "emission wavelength",
        "半峰宽", "FWHM",
        "斯托克斯位移", "Stokes shift",
        "载流子迁移率", "carrier mobility",
        "功函数", "work function",
        "厚度", "thickness",
        "层数", "number of layers",
        "扭角", "twist angle",
        "魔角", "magic angle",
        "拉曼", "Raman", "G 峰", "2D 峰",
        "AFM", "针尖",
        "STM", "扫描隧道",
        "孔径", "pore size",
        "孔体积", "pore volume",
    ],
    "domain_keywords": [
        "光催化", "photocatalysis",
        "光催化产氢", "photocatalytic HER",
        "光催化 CO2 还原",
        "柔性显示", "flexible display",
        "OLED", "QLED",
        "传感器", "sensor",
        "气体传感", "gas sensing",
        "生物传感", "biosensor",
        "光伏", "photovoltaics", "PV",
        "钙钛矿太阳能", "perovskite solar",
        "超级电容器", "supercapacitor",
        "锂硫电池", "Li-S battery",
        "钠离子电池", "Na-ion battery",
        "光致发光", "photoluminescence", "PL",
        "电致发光", "electroluminescence", "EL",
        "单光子发射", "single photon emission",
        "量子信息", "quantum information",
        "抗菌", "antibacterial",
        "靶向药物", "targeted drug",
        "组织工程支架", "tissue scaffold",
    ],
    "gen_backend": "diffusion_nano",     # 纳米结构扩散生成(Stage 2 接 diffusion_nano)
    "sim_backend": "orbnet_dft",         # OrbNet-DFT(纳米 DFT)
    "hpc_engine": "cp2k",                # CP2K 第一性原理 MD(大体系纳米)
    "lit_backend": "mock_nano",          # W15 mock,Stage 2 arXiv + NanoHUB
    "exp_methods": [
        "CVD", "化学气相沉积",
        "ALD", "原子层沉积",
        "PVD", "物理气相沉积",
        "磁控溅射", "magnetron sputtering",
        "热分解", "thermal decomposition",
        "湿化学合成", "wet chemical synthesis",
        "胶体合成", "colloidal synthesis",
        "机械剥离", "mechanical exfoliation",
        "液相剥离", "liquid exfoliation",
        "CVD 生长", "CVD growth",
        "PLD", "脉冲激光沉积",
        "LB 膜", "Langmuir-Blodgett",
        "微流控合成", "microfluidic synthesis",
        "AFM 表征",
        "TEM 高分辨", "HRTEM",
        "STEM",
        "拉曼 mapping",
        "PL mapping",
        "XPS",
        "UPS",
        "BET 比表面积",
    ],
    "unit_cost": {
        "mat-gen-agent": 0.08,            # ¥/纳米结构(diffusion 较贵)
        "mat-sim-agent": 0.4,             # ¥/候选(OrbNet 接近 CHGNet)
        "mat-hpc-agent": 80.0,            # ¥/job(CP2K 比 VASP 略便宜)
        "mat-exp-agent": 20.0,            # ¥/样品(CVD/ALD/PVD 设备贵)
        "mat-critic-agent": 0.05,
        "mat-bayesian-agent": 0.02,
        "mat-lit-agent": 0.1,
        "mat-intent-agent": 0.01,
        "mat-cost-agent": 0.001,
        "mat-data-lineage-agent": 0.001,
    },
}


# W17: 金属 / 合金 profile(W17 新增)
METAL_ALLOY_PROFILE: dict[str, Any] = {
    "name": "metal_alloy",
    "display_name_zh": "金属 / 合金",
    "description": "金属与合金(钢 / 不锈钢 / 钛合金 / 镍基超合金 / 高熵合金 / 形状记忆合金 / 非晶合金 / 铝合金 / 镁合金 / 铜合金 ...)",
    "elements": [
        # 黑色金属(铁基)
        "Fe", "C", "Mn", "Si", "Cr", "Ni", "Mo", "V", "Nb",
        "Ti", "Al", "Co", "Cu", "W",
        # 有色金属
        "Mg", "Al", "Ti", "Cu", "Zn", "Ni",
        "Pb", "Sn", "Zr", "Be",
        # 高温合金常见掺杂
        "Hf", "Ta", "Re", "Y",
        # 杂质
        "S", "P", "O", "N", "H",
    ],
    "material_aliases": [
        # 结构钢
        "stainless", "304", "316", "316L", "321", "310",
        # 钛合金
        "Ti-6Al-4V", "Ti-5553", "Ti-Al",
        # 镍基超合金
        "Inconel", "Inconel 718", "Inconel 625",
        "Hastelloy", "Rene", "Rene 65", "CMSX", "PWA",
        # 高熵合金
        "HEA", "Cantor", "Senkov",
        # 形状记忆
        "Nitinol", "NiTi", "Cu-Zn-Al", "Cu-Al-Ni",
        # 非晶合金
        "metallic glass", "Metglas",
        # 铝合金
        "2024", "7075", "6061",
        # 工具钢
        "M2", "M42", "H13", "D2",
    ],
    "property_keywords": [
        "屈服强度", "yield strength",
        "抗拉强度", "UTS", "ultimate tensile strength",
        "断后伸长率", "elongation",
        "断面收缩率", "reduction of area",
        "夏比冲击", "Charpy",
        "断裂韧性", "K_IC", "fracture toughness",
        "硬度", "HB", "HV", "HRC", "HRB",
        "蠕变", "creep",
        "持久强度", "stress rupture",
        "疲劳极限", "fatigue limit",
        "S-N 曲线", "S-N curve",
        "应力腐蚀", "SCC", "stress corrosion cracking",
        "相图", "phase diagram",
        "TTT", "CCT",
        "固溶处理", "solution treatment",
        "时效", "aging", "aging hardening",
        "马氏体", "martensite",
        "奥氏体", "austenite",
        "珠光体", "pearlite",
        "贝氏体", "bainite",
        "铁素体", "ferrite",
        "渗碳体", "cementite",
        "析出相", "γ' 相", "γ\" 相",
        "再结晶", "recrystallization",
        "热加工", "hot working",
    ],
    "domain_keywords": [
        "航空航天", "aerospace",
        "燃气轮机", "gas turbine",
        "核电", "nuclear",
        "汽车", "automotive",
        "船舶", "marine",
        "桥梁", "bridge",
        "建筑", "construction",
        "压力容器", "pressure vessel",
        "管道", "pipeline",
        "轴承", "bearing",
        "齿轮", "gear",
        "紧固件", "fastener",
        "3D 打印金属", "metal AM",
        "SLM", "LPBF", "EBM", "DED",
        "锻造", "forging",
        "铸造", "casting",
        "轧制", "rolling",
        "焊接", "welding",
        "热等静压", "HIP",
        "粉末冶金", "P/M",
    ],
    "gen_backend": "alloy_diffusion",     # W17: 合金成分扩散生成(Stage 2 接 DiffCSP / CDVAE-alloy)
    "sim_backend": "chgnet_metal",        # CHGNet 本来就支持 metal(per W4),复用
    "hpc_engine": "vasp_metal",           # VASP 合金(special k-point + SQS)
    "lit_backend": "mock_alloy",          # W17 mock,Stage 2 arXiv + Springer Materials
    "exp_methods": [
        "铸造", "casting",
        "锻造", "forging",
        "轧制", "rolling",
        "挤压", "extrusion",
        "拉拔", "drawing",
        "粉末冶金", "P/M",
        "热等静压", "HIP",
        "选择性激光熔化", "SLM",
        "电子束熔化", "EBM",
        "定向凝固", "directional solidification",
        "热处理", "heat treatment",
        "正火", "normalizing",
        "退火", "annealing",
        "淬火", "quenching",
        "回火", "tempering",
        "固溶+时效", "solution+aging",
        "化学热处理", "渗碳", "渗氮",
        "焊接", "welding",
        "硬度测试", "HB/HV/HRC",
        "拉伸试验", "tensile test",
        "冲击试验", "Charpy",
        "疲劳试验",
        "蠕变试验",
        "金相", "metallography",
        "SEM",
        "TEM",
        "EBSD",
        "XRD",
        "DSC",
    ],
    "unit_cost": {
        # W17 metal_alloy 单价表 — 大体低于 inorganic_crystal(VASP 不重,SEM/EBSD 便宜)
        "mat-gen-agent": 0.04,            # ¥/候选(CDM 比 MatterGen 简单)
        "mat-sim-agent": 0.3,             # ¥/候选(CHGNet)
        "mat-hpc-agent": 50.0,            # ¥/job(SQS 超胞 VASP,比纯晶体便宜)
        "mat-exp-agent": 30.0,            # ¥/样品(机加工 + 拉伸样 + 热处理)
        "mat-critic-agent": 0.05,
        "mat-bayesian-agent": 0.02,
        "mat-lit-agent": 0.1,
        "mat-intent-agent": 0.01,
        "mat-cost-agent": 0.001,
        "mat-data-lineage-agent": 0.001,
    },
}


# ============================================================================
# 域 profile 注册表
# ============================================================================


PROFILES: dict[str, dict[str, Any]] = {
    "inorganic_crystal": INORGANIC_CRYSTAL_PROFILE,
    "polymer": POLYMER_PROFILE,
    "nano": NANO_PROFILE,
    "metal_alloy": METAL_ALLOY_PROFILE,   # W17 新增
}


# ============================================================================
# 域 backend / 单价路由函数
# ============================================================================


def get_profile(domain: str) -> dict[str, Any]:
    """获取指定域的完整 profile

    Args:
        domain: 3 域之一

    Returns:
        profile dict

    Raises:
        ValueError: 未知 domain
    """
    p = PROFILES.get(domain)
    if p is None:
        valid = ", ".join(PROFILES.keys())
        raise ValueError(f"未知材料域 '{domain}',有效: {valid}")
    return p


def get_gen_backend(domain: str) -> str:
    """获取 gen_backend(W2 mat-gen 路由)"""
    return get_profile(domain)["gen_backend"]


def get_sim_backend(domain: str) -> str:
    """获取 sim_backend(W4 mat-sim 路由)"""
    return get_profile(domain)["sim_backend"]


def get_hpc_engine(domain: str) -> str:
    """获取 hpc_engine(W5 mat-hpc 路由)"""
    return get_profile(domain)["hpc_engine"]


def get_lit_backend(domain: str) -> str:
    """获取 lit_backend(W14 mat-lit 路由)"""
    return get_profile(domain)["lit_backend"]


def get_unit_cost_table(domain: str) -> dict[str, float]:
    """获取指定域的单价表(W14 mat-cost 路由)"""
    return dict(get_profile(domain)["unit_cost"])


__all__ = [
    "INORGANIC_CRYSTAL_PROFILE",
    "METAL_ALLOY_PROFILE",
    "NANO_PROFILE",
    "POLYMER_PROFILE",
    "PROFILES",
    "get_gen_backend",
    "get_hpc_engine",
    "get_lit_backend",
    "get_profile",
    "get_sim_backend",
    "get_unit_cost_table",
]