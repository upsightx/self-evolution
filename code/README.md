# FreeTodo 精华提取

从 FreeTodo (LifeTrace) 项目中提取的可复用设计模式和 prompt 模板。
原项目已卸载（2026-03-18），此目录保留有参考价值的部分。

## 目录结构

```
freetodo-essence/
├── README.md              # 本文件
├── patterns.md            # 可复用的设计模式
├── prompts/
│   ├── todo-extraction.md # 待办提取 prompt（从对话中识别待办）
│   ├── rag-pipeline.md    # RAG 流程 prompt
│   ├── task-planning.md   # 任务拆解 prompt
│   └── intent-classify.md # 意图分类 prompt
└── code/
    ├── prompt_loader.py   # YAML prompt 加载器（单例）
    ├── query_parser.py    # 自然语言查询解析器
    ├── context_builder.py # RAG 上下文构建器
    └── module_registry.py # 声明式模块注册
```

## 丢弃的部分

- vector_db/vector_service — chromadb 封装，我们有 memory_db
- ocr/auto_todo_detection — 依赖截图，不适用
- tavily_client/web_search — 已有 web_search 工具
- token_usage_logger — OpenClaw 自带 usage 追踪
- config_watcher/lazy_services — FreeTodo 专用
- chat_service/todo_service — 业务耦合太深
- agno_tools prompts — Agent 框架专用
