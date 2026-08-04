"""materials_project_client — Materials Project 真实 API 客户端(W17-C)

复用 W16 arXiv client 架构(W17 价值密度:同模式第 2 个真实 API)

支持:
- 真查 Materials Project(Materials API REST,无需 token)
- 失败 fallback(连接失败 / timeout / 404)
- 3 域 + metal_alloy 域关键词构造

Materials Project API 文档:
- https://materialsproject.org/wiki/index.php/The_Materials_API
- https://api.materialsproject.org/ (v3 API,无需 token 公开查询)
"""

from .client import (
    MATERIALS_PROJECT_BASE_URL,
    MATERIALS_PROJECT_TIMEOUT_SEC,
    MaterialsProjectClient,
    MaterialsProjectReference,
    is_materials_project_available,
    search_materials_project,
)

__all__ = [
    "MATERIALS_PROJECT_BASE_URL",
    "MATERIALS_PROJECT_TIMEOUT_SEC",
    "MaterialsProjectClient",
    "MaterialsProjectReference",
    "is_materials_project_available",
    "search_materials_project",
]
