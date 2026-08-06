"""arxiv_client / client.py — arXiv API 真接入(W16) + LRU cache(v1.3.2-Academic)

支持:
- 真查 arXiv(urllib + Atom XML 解析)
- 失败 fallback(连接失败 / timeout / parse 错误)
- 3 域关键词构造(per W15 MaterialDomainRouter)
- LRU cache(per v1.3.2-Academic M1)— 同 query < 1ms 命中
- gzip 解压(per v1.3.2-Academic M1)— 大响应省流量

arXiv API 文档:https://info.arxiv.org/help/api/basics.html

Stage 1 行为(W14): mock DB
Stage 2 行为(W16): 默认真查 arXiv,失败 fallback
Stage 2.1 行为(v1.3.2): 加 LRU cache + gzip 支持

per MatWAU-v1.3.2-Academic-dev-plan-20260806.md §三 M1
"""
from __future__ import annotations

import gzip
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

ARXIV_API_URL = "http://export.arxiv.org/api/query"
ARXIV_NAMESPACE = "{http://www.w3.org/2005/Atom}"
ARXIV_TIMEOUT_SEC = 8  # 单次 query timeout
ARXIV_LRU_CACHE_DEFAULT_SIZE = 128  # v1.3.2 M1: LRU cache 默认容量


@dataclass
class ArxivReference:
    """1 篇 arXiv 论文的引用(per W14 LitReference 子集)

    Attributes:
        arxiv_id: arXiv ID(如 "2401.12345")
        title: 论文标题
        authors: 作者列表
        year: 出版年份
        summary: 摘要(前 1000 字符)
        url: arXiv URL
        categories: arXiv 分类列表
    """

    arxiv_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int = 2024
    summary: str = ""
    url: str = ""
    categories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "summary": self.summary[:200],
            "url": self.url,
            "categories": self.categories,
        }


# ============================================================================
# v1.3.2-Academic M1: LRU cache(per mat-arxiv 复用 nomad_client 模式)
# ============================================================================


class _LruCache:
    """线程不安全 LRU cache(per nomad_client 实现)

    MatWAU 调用都是单线程 OK;若多线程需外加 threading.Lock。

    Attributes:
        _capacity: 最大容量
        _data: OrderedDict(key → list[ArxivReference])
    """

    def __init__(self, capacity: int = ARXIV_LRU_CACHE_DEFAULT_SIZE):
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        self._capacity = capacity
        self._data: OrderedDict[str, list[ArxivReference]] = OrderedDict()

    def get(self, key: str) -> list[ArxivReference] | None:
        """cache hit → 返回 + move to end(LRU 维护);miss → None"""
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: str, refs: list[ArxivReference]) -> None:
        """写入 + 超容量时 pop 最旧"""
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = list(refs)
        if len(self._data) > self._capacity:
            self._data.popitem(last=False)  # FIFO pop 最旧

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        """清空(per 测试用)"""
        self._data.clear()


def is_arxiv_available() -> bool:
    """检查 arXiv 是否可达(轻量 ping)"""
    try:
        url = ARXIV_API_URL + "?" + urllib.parse.urlencode({
            "search_query": "all:test",
            "max_results": "1",
        })
        req = urllib.request.Request(url, headers={"User-Agent": "MatWAU/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _parse_arxiv_xml(xml_text: str) -> list[ArxivReference]:
    """解析 arXiv Atom XML → List[ArxivReference]

    Args:
        xml_text: arXiv API 返回的 XML 文本

    Returns:
        论文列表
    """
    refs = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("arXiv XML 解析失败: %s", e)
        return refs

    for entry in root.findall(f"{ARXIV_NAMESPACE}entry"):
        arxiv_id = ""
        id_el = entry.find(f"{ARXIV_NAMESPACE}id")
        if id_el is not None and id_el.text:
            # URL 形式: http://arxiv.org/abs/2401.12345v1
            m = re.search(r"abs/([\d.]+)", id_el.text)
            if m:
                arxiv_id = m.group(1)

        title_el = entry.find(f"{ARXIV_NAMESPACE}title")
        title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else ""

        summary_el = entry.find(f"{ARXIV_NAMESPACE}summary")
        summary = summary_el.text.strip() if summary_el is not None and summary_el.text else ""

        published_el = entry.find(f"{ARXIV_NAMESPACE}published")
        year = 2024
        if published_el is not None and published_el.text:
            m = re.search(r"(\d{4})", published_el.text)
            if m:
                year = int(m.group(1))

        authors = []
        for author_el in entry.findall(f"{ARXIV_NAMESPACE}author"):
            name_el = author_el.find(f"{ARXIV_NAMESPACE}name")
            if name_el is not None and name_el.text:
                authors.append(name_el.text)

        categories = []
        for cat_el in entry.findall(f"{ARXIV_NAMESPACE}category"):
            term = cat_el.get("term")
            if term:
                categories.append(term)

        if arxiv_id and title:
            refs.append(ArxivReference(
                arxiv_id=arxiv_id,
                title=title,
                authors=authors,
                year=year,
                summary=summary,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                categories=categories,
            ))

    return refs


def _build_arxiv_query(user_intent: str, *, domain: str | None = None) -> str:
    """构造 arXiv search_query

    策略:
    - 提取引号内容 / 大写 alias / 化学式 → 高优先级字段
    - 简化成 arXiv 兼容的 search_query
    - domain-specific 关键词加权(per W15 MaterialDomainRouter)
    - v1.3.4-Academic hotfix: 中英混合 / 纯中文 query 自动翻译成英文关键词
      (因为 arXiv API 对中文字符搜索命中率 ≈ 0,fallback 到 mock)

    Examples:
        "出 LiCoO2 实验方案" → ti:LiCoO2 OR abs:LiCoO2
        "算 PMMA 玻璃化转变温度" → ti:PMMA AND ti:glass
        "设计 CdSe 量子点" → ti:CdSe AND ti:quantum
        "钙钛矿太阳能电池 长期稳定性" → ti:perovskite OR abs:perovskite OR ti:solar OR ...
    """
    msg = user_intent

    # 提取化学式(简单规则:大写 + 小写 + 数字,如 LiCoO2 / CdSe / PMMA)
    formulas = re.findall(r"\b[A-Z][a-z]?\d*(?:[A-Z][a-z]?\d*)+\b|\b[A-Z][a-z]?\d{2,}\b", msg)
    formulas = [f for f in formulas if len(f) >= 4]  # 过滤太短的(如 Li)

    # 提取大写 alias(LLZO / LFP / NMC / ...)
    aliases = re.findall(r"\b[A-Z]{2,6}[0-9]{0,4}\b", msg)
    aliases = [a for a in aliases if a not in formulas and len(a) >= 3]

    # 提取属性词(per domain keyword 库,简化)
    prop_keywords = []
    domain_keywords_map = {
        "inorganic_crystal": ["ionic conductivity", "lattice", "DFT", "formation energy", "cathode"],
        "polymer": ["glass transition", "Tg", "tensile strength", "polymer", "PMMA"],
        "nano": ["quantum dot", "graphene", "MoS2", "nanoparticle", "BET"],
    }
    msg_lower = msg.lower()
    for kw in domain_keywords_map.get(domain or "inorganic_crystal", []):
        if kw.lower() in msg_lower:
            prop_keywords.append(kw)

    # 构造 query
    parts = []
    if formulas:
        for f in formulas[:3]:  # 最多 3 个化学式
            parts.append(f'(ti:{f} OR abs:{f})')
    if aliases:
        for a in aliases[:3]:
            parts.append(f'(ti:{a} OR abs:{a})')
    if prop_keywords:
        for kw in prop_keywords[:2]:
            parts.append(f'(ti:"{kw}" OR abs:"{kw}")')

    # v1.3.4-Academic hotfix: 中→英关键词翻译
    # arXiv API 对中文字符搜索命中率 ≈ 0,fallback 到 mock 让中文用户以为"假接 arxiv"
    # 解法:检测到中文 → 查表转英文 → 加到 query 里
    has_chinese = bool(re.search(r"[一-鿿]", msg))
    if has_chinese:
        chinese_translations = _extract_chinese_translations(msg)
        for en in chinese_translations[:5]:  # 最多 5 个英文翻译
            parts.append(f'(ti:"{en}" OR abs:"{en}")')

    # 兜底:用整句作为 abs 兜底搜索
    if not parts:
        # 用最关键的几个词
        words = re.findall(r"\b[A-Za-z]{3,}\b|\b[一-鿿]{2,}\b", msg)
        if words:
            parts.append(f'(abs:"{words[0]}")')

    return " OR ".join(parts) if parts else "all:" + msg[:50]


# v1.3.4-Academic — 中→英关键词映射表(材料科学常用词)
# 排序:长的在前,避免短词误匹配(如"电池"先匹配再匹配"锂电池")
CHINESE_TO_ENGLISH_KEYWORDS = [
    # ============ 化合物 / 材料(长词优先)============
    ("固态电解质", "solid electrolyte"),
    ("液态电解质", "liquid electrolyte"),
    ("钙钛矿太阳能电池", "perovskite solar cell"),
    ("钙钛矿", "perovskite"),
    ("石墨烯", "graphene"),
    ("碳纳米管", "carbon nanotube"),
    ("硅碳负极", "silicon-carbon anode"),
    ("硅基负极", "silicon anode"),
    ("锂电池", "lithium-ion battery"),
    ("固态电池", "solid state battery"),
    ("钠电池", "sodium-ion battery"),
    ("燃料电池", "fuel cell"),
    ("硫化物", "sulfide"),
    ("氧化物", "oxide"),
    ("氮化物", "nitride"),
    ("碳化物", "carbide"),
    ("硼化物", "boride"),
    ("硅酸盐", "silicate"),
    ("磷酸盐", "phosphate"),
    # ============ 元素 / 金属(短词)============
    ("锂", "lithium"),
    ("钠", "sodium"),
    ("镁", "magnesium"),
    ("锌", "zinc"),
    ("铝", "aluminum"),
    ("铜", "copper"),
    ("铁", "iron"),
    ("钴", "cobalt"),
    ("镍", "nickel"),
    ("锰", "manganese"),
    ("硅", "silicon"),
    # ============ 应用 / 器件 ============
    ("太阳能电池", "solar cell"),
    ("太阳能", "solar"),
    ("电池", "battery"),
    ("正极材料", "cathode material"),
    ("正极", "cathode"),
    ("负极材料", "anode material"),
    ("负极", "anode"),
    ("电解质", "electrolyte"),
    ("隔膜", "separator"),
    ("催化", "catalyst"),
    ("催化剂", "catalyst"),
    ("传感器", "sensor"),
    ("存储", "storage"),
    ("陶瓷", "ceramic"),
    ("玻璃", "glass"),
    ("合金", "alloy"),
    ("半导体", "semiconductor"),
    ("超导体", "superconductor"),
    # ============ 属性 / 性能 ============
    ("长期稳定性", "long-term stability"),
    ("稳定性", "stability"),
    ("形成能", "formation energy"),
    ("带隙", "band gap"),
    ("电导率", "conductivity"),
    ("离子电导率", "ionic conductivity"),
    ("能量密度", "energy density"),
    ("比容量", "specific capacity"),
    ("容量", "capacity"),
    ("电压", "voltage"),
    ("硬度", "hardness"),
    ("磁性", "magnetic"),
    ("超导", "superconducting"),
    ("介电", "dielectric"),
    ("压电", "piezoelectric"),
    ("热导", "thermal conductivity"),
    ("光学", "optical"),
    ("吸附", "adsorption"),
    ("扩散", "diffusion"),
    ("弹性", "elastic"),
    ("强度", "strength"),
    # ============ 方法 / 表征 ============
    ("第一性原理", "first-principles"),
    ("分子动力学", "molecular dynamics"),
    ("蒙特卡洛", "Monte Carlo"),
    ("机器学习", "machine learning"),
    ("深度学习", "deep learning"),
    ("高通量", "high-throughput"),
    ("材料基因组", "materials genome"),
    ("表征", "characterization"),
    ("实验", "experiment"),
    ("模拟", "simulation"),
    ("合成", "synthesis"),
    ("制备", "fabrication"),
    # ============ 文档类型 / 修饰 ============
    ("综述", "review"),
    ("进展", "progress"),
    ("最新", "recent"),
    ("研究", "research"),
    ("论文", "paper"),
    # ============ 结构 / 形貌 ============
    ("界面", "interface"),
    ("缺陷", "defect"),
    ("掺杂", "doping"),
    ("薄膜", "thin film"),
    ("纳米", "nano"),
    ("纳米结构", "nanostructure"),
    ("微结构", "microstructure"),
    ("异质结", "heterojunction"),
    ("晶界", "grain boundary"),
    ("晶体结构", "crystal structure"),
    # ============ 其他 ============
    ("高温", "high temperature"),
    ("低温", "low temperature"),
    ("高压", "high pressure"),
    ("复合材料", "composite material"),
    ("高分子", "polymer"),
    ("聚合物", "polymer"),
]


def _extract_chinese_translations(msg: str) -> list[str]:
    """从 msg 中匹配中文短语 → 翻译列表(去重 + 长词优先匹配)

    去重策略:Chinese substring dedup — 如果一个中文短语的翻译已被更长的中文
    短语覆盖,则跳过。例如 "钙钛矿太阳能电池" 翻译成 "perovskite solar cell"
    后,"钙钛矿/太阳能/电池" 单独的翻译被丢弃(被长词覆盖)。

    Args:
        msg: 用户原始 query(含中文 + 英文)

    Returns:
        List[str]: 翻译出的英文短语(按 CHINESE_TO_ENGLISH_KEYWORDS 表的顺序,
                  即长词优先),自动去重
    """
    matched_cn: list[str] = []  # 顺序记录匹配的中文短语(去重)
    seen_cn: set[str] = set()
    for cn, _en in CHINESE_TO_ENGLISH_KEYWORDS:
        if cn in msg and cn not in seen_cn:
            matched_cn.append(cn)
            seen_cn.add(cn)

    # 去重:短词如果已经被前面的长词包含,则跳过
    # (per Chinese substring dedup,而非 English substring dedup)
    final_cn: list[str] = []
    for cn in matched_cn:
        # 检查是否已有更长的 cn 包含当前 cn(中文 substring)
        covered = any(
            (other != cn) and (cn in other)
            for other in matched_cn
            if other in final_cn  # 已在 final 列表里(更长的)
        )
        if not covered:
            final_cn.append(cn)

    # 转英文 + dedup English
    translations: list[str] = []
    seen_en: set[str] = set()
    for cn in final_cn:
        for table_cn, en in CHINESE_TO_ENGLISH_KEYWORDS:
            if table_cn == cn and en not in seen_en:
                translations.append(en)
                seen_en.add(en)
                break
    return translations


@dataclass
class ArxivClient:
    """arXiv API 客户端(W16 Stage 2 真接入 + v1.3.2 LRU cache + gzip)

    Attributes:
        timeout: 单次请求超时(秒,默认 8)
        user_agent: User-Agent 头(arXiv 要求标识)
        enable_fallback: 真查询失败时是否降级到 mock
        max_results: 默认 max_results(每个 query)
        cache_size: v1.3.2 LRU cache 容量(默认 128)
        enable_cache: v1.3.2 是否启用 LRU cache(默认 True)
        enable_gzip: v1.3.2 是否启用 gzip 压缩(默认 True)
        hard_max_results: v1.3.2 max_results 上限保护(防滥用,默认 20)
    """

    timeout: int = 8
    user_agent: str = "MatWAU/1.0 (research; mailto:contact@matwau.local)"
    enable_fallback: bool = True
    max_results: int = 5
    cache_size: int = ARXIV_LRU_CACHE_DEFAULT_SIZE  # v1.3.2 M1
    enable_cache: bool = True  # v1.3.2 M1
    enable_gzip: bool = True  # v1.3.2 M1
    hard_max_results: int = 20  # v1.3.2 M1: arxiv max_results 上限保护

    def __post_init__(self):
        """初始化 LRU cache(v1.3.2 M1)"""
        self._cache: _LruCache | None = (
            _LruCache(capacity=self.cache_size) if self.enable_cache else None
        )

    def _cache_key(self, user_intent: str, max_results: int, domain: str | None) -> str:
        """构造 cache key(per user_intent + max_results + domain)"""
        return f"{user_intent.strip()}|{max_results}|{domain or 'default'}"

    def search(
        self,
        user_intent: str,
        *,
        max_results: int | None = None,
        domain: str | None = None,
    ) -> tuple[list[ArxivReference], bool]:
        """查 arXiv,返回 (references, is_real_query)

        Args:
            user_intent: 用户原始意图
            max_results: 最多返回多少篇(None → 用 self.max_results,超过 hard_max_results 截断)
            domain: 材料域(per W15)

        Returns:
            (refs, is_real_query)
            - is_real_query=True:真 arXiv 返回(或 LRU cache 命中)
            - is_real_query=False:fallback(网络失败 / 解析失败)
        """
        max_results = max_results or self.max_results
        # v1.3.2 M1: 硬上限保护
        if max_results > self.hard_max_results:
            logger.warning(
                "arXiv max_results=%d 超硬上限 %d, 截断",
                max_results, self.hard_max_results,
            )
            max_results = self.hard_max_results

        # v1.3.2 M1: LRU cache 命中检查
        cache_key = self._cache_key(user_intent, max_results, domain)
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug("arXiv cache hit: %s", cache_key)
                return cached, True

        query = _build_arxiv_query(user_intent, domain=domain)

        url = ARXIV_API_URL + "?" + urllib.parse.urlencode({
            "search_query": query,
            "max_results": str(max_results),
            "sortBy": "relevance",
            "sortOrder": "descending",
        })

        try:
            # v1.3.2 M1: 加 Accept-Encoding: gzip
            headers = {"User-Agent": self.user_agent}
            if self.enable_gzip:
                headers["Accept-Encoding"] = "gzip"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"arXiv 返回 {resp.status}")
                raw_bytes = resp.read()
                # v1.3.2 M1: gzip 解压
                content_encoding = resp.headers.get("Content-Encoding", "").lower()
                if "gzip" in content_encoding:
                    try:
                        xml_text = gzip.decompress(raw_bytes).decode("utf-8", errors="ignore")
                    except Exception as e:
                        logger.warning("arXiv gzip 解压失败: %s", e)
                        # fallback 到 raw bytes 解码
                        xml_text = raw_bytes.decode("utf-8", errors="ignore")
                else:
                    xml_text = raw_bytes.decode("utf-8", errors="ignore")

            refs = _parse_arxiv_xml(xml_text)
            if not refs:
                # arXiv 偶尔返回空(所有 entry 都解析失败)
                raise RuntimeError("arXiv 返回 0 篇")

            # v1.3.2 M1: 写入 LRU cache
            if self._cache is not None:
                self._cache.put(cache_key, refs)

            return refs[:max_results], True

        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            logger.warning("arXiv 网络失败: %s", e)
        except Exception as e:
            logger.warning("arXiv 解析失败: %s", e)

        # Fallback:返回空,标记 is_real_query=False(让调用方决定用 mock DB)
        return [], False

    def clear_cache(self) -> None:
        """清 LRU cache(v1.3.2 M1,per 测试 / 显式 invalidate 用)"""
        if self._cache is not None:
            self._cache.clear()


def search_arxiv(
    user_intent: str,
    *,
    max_results: int = 5,
    domain: str | None = None,
    client: ArxivClient | None = None,
) -> tuple[list[ArxivReference], bool]:
    """便利函数:查 arXiv

    Returns:
        (refs, is_real_query)
    """
    c = client or ArxivClient()
    return c.search(user_intent, max_results=max_results, domain=domain)


__all__ = [
    "ARXIV_API_URL",
    "ARXIV_LRU_CACHE_DEFAULT_SIZE",
    "ArxivClient",
    "ArxivReference",
    "is_arxiv_available",
    "search_arxiv",
]  # type: ignore[name-defined]