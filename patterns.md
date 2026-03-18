# 可复用设计模式

## 1. 声明式模块注册（Module Registry）

用 dataclass 声明模块，启动时自动扫描、检查依赖、按序加载。
适合需要插件化架构的 FastAPI/Flask 项目。

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ModuleDefinition:
    id: str
    router_module: str          # 如 "app.routers.chat"
    router_attr: str = "router" # 模块中的 router 变量名
    dependencies: tuple[str, ...] = ()  # 依赖的其他模块 id
    requires: tuple[str, ...] = ()      # 依赖的 Python 包
    core: bool = False                   # 核心模块不可禁用

MODULES = (
    ModuleDefinition(id="health", router_module="app.routers.health", core=True),
    ModuleDefinition(id="chat", router_module="app.routers.chat", requires=("openai",)),
    ModuleDefinition(id="search", router_module="app.routers.search", dependencies=("chat",)),
)

def register_modules(app, modules):
    """按依赖顺序加载模块，缺依赖的跳过"""
    loaded = set()
    for mod in modules:
        # 检查 Python 依赖
        if mod.requires:
            missing = [r for r in mod.requires if not importlib.util.find_spec(r)]
            if missing:
                print(f"Skip {mod.id}: missing {missing}")
                continue
        # 检查模块依赖
        if not all(d in loaded for d in mod.dependencies):
            print(f"Skip {mod.id}: unmet deps {mod.dependencies}")
            continue
        # 动态导入并注册
        module = importlib.import_module(mod.router_module)
        router = getattr(module, mod.router_attr)
        app.include_router(router)
        loaded.add(mod.id)
```

## 2. YAML Prompt 加载器（单例）

从目录加载所有 YAML prompt 文件，支持变量替换。

```python
import yaml
from pathlib import Path

class PromptLoader:
    _instance = None
    _prompts = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self, prompts_dir: str):
        """从目录加载所有 .yaml 文件"""
        for f in Path(prompts_dir).glob("*.yaml"):
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
                self._prompts.update(data)

    def get(self, key: str, **kwargs) -> str:
        """获取 prompt，支持 {var} 替换"""
        parts = key.split(".")
        val = self._prompts
        for p in parts:
            val = val[p]
        return val.format(**kwargs) if kwargs else val
```

## 3. RAG 流程（Intent → Retrieve → Build Context → Generate）

四步流水线，每步可独立替换：

```
用户查询 → 意图分类 → 数据检索 → 上下文构建 → LLM 生成
              ↓            ↓            ↓
         direct/rag/    SQL/向量/     截断+分组
         stats/help     混合检索     优先级排序
```

核心设计：
- 意图分类先走规则（关键词匹配），失败再走 LLM
- 上下文构建有 max_context_length 硬限制，超长自动截断
- 检索结果按时间分组，每组取 top-N

## 4. 自然语言查询解析器

从用户输入中提取结构化查询条件：

```python
@dataclass
class QueryConditions:
    start_time: datetime | None = None
    end_time: datetime | None = None
    app_names: list[str] | None = None
    keywords: list[str] | None = None
    query_type: str = "general"

class QueryParser:
    # 时间模式：支持 "今天"、"昨天"、"上周"、"最近3天" 等
    TIME_PATTERNS = {
        r"今天": lambda: (today_start, today_end),
        r"昨天": lambda: (yesterday_start, yesterday_end),
        r"最近(\d+)天": lambda m: (now - timedelta(days=int(m.group(1))), now),
        r"上周": lambda: (last_week_start, last_week_end),
    }

    def parse(self, query: str) -> QueryConditions:
        """先规则解析，失败再 LLM 解析"""
        result = self._parse_with_rules(query)
        if result.query_type == "general" and self.llm_client:
            result = self._parse_with_llm(query)
        return result
```

## 5. 上下文构建器（Context Builder）

控制送入 LLM 的上下文大小和质量：

```python
class ContextBuilder:
    def __init__(self, max_context_length=8000):
        self.max_length = max_context_length

    def build(self, query, records):
        # 1. 按相关性排序
        ranked = self._rank_by_relevance(records, query)
        # 2. 按时间分组
        grouped = self._group_by_time(ranked)
        # 3. 每组取 top-N，拼接
        context_parts = []
        for group in grouped:
            context_parts.extend(group[:5])
        # 4. 截断到 max_length
        return self._truncate(context_parts)

    def _truncate(self, parts):
        """从后往前删，保留最相关的"""
        text = "\n".join(parts)
        while len(text) > self.max_length and parts:
            parts.pop()
            text = "\n".join(parts)
        return text
```
