"""声明式模块注册器

用 dataclass 声明模块定义，启动时自动检查依赖并按序加载。
适用于 FastAPI 插件化架构。

用法：
    app = FastAPI()
    registry = ModuleRegistry(MODULES)
    registry.register_all(app)
"""

import importlib
import importlib.util
from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleDefinition:
    id: str                              # 模块唯一标识
    router_module: str                   # Python 模块路径，如 "app.routers.chat"
    router_attr: str = "router"          # 模块中 router 变量名
    dependencies: tuple[str, ...] = ()   # 依赖的其他模块 id
    requires: tuple[str, ...] = ()       # 依赖的 Python 包
    core: bool = False                   # 核心模块不可禁用


class ModuleRegistry:
    def __init__(self, modules: tuple[ModuleDefinition, ...]):
        self.modules = modules
        self.loaded: set[str] = set()
        self.skipped: dict[str, str] = {}  # id → skip reason

    def register_all(self, app) -> dict[str, str]:
        """注册所有模块到 FastAPI app，返回跳过的模块及原因"""
        for mod in self.modules:
            self._try_register(app, mod)
        return self.skipped

    def _try_register(self, app, mod: ModuleDefinition) -> bool:
        """尝试注册单个模块"""
        # 检查 Python 包依赖
        if mod.requires:
            missing = [r for r in mod.requires if not importlib.util.find_spec(r)]
            if missing:
                reason = f"missing packages: {missing}"
                self.skipped[mod.id] = reason
                if mod.core:
                    raise RuntimeError(f"Core module {mod.id} failed: {reason}")
                return False

        # 检查模块依赖
        unmet = [d for d in mod.dependencies if d not in self.loaded]
        if unmet:
            reason = f"unmet dependencies: {unmet}"
            self.skipped[mod.id] = reason
            return False

        # 动态导入并注册
        try:
            module = importlib.import_module(mod.router_module)
            router = getattr(module, mod.router_attr)
            app.include_router(router)
            self.loaded.add(mod.id)
            return True
        except Exception as e:
            reason = f"import error: {e}"
            self.skipped[mod.id] = reason
            if mod.core:
                raise
            return False

    def get_status(self) -> dict:
        """返回模块加载状态"""
        return {
            "loaded": sorted(self.loaded),
            "skipped": self.skipped,
            "total": len(self.modules),
        }
