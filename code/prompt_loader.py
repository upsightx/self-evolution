"""YAML Prompt 加载器（单例模式）

从目录加载所有 .yaml prompt 文件，支持点号路径访问和变量替换。
零依赖（仅 pyyaml）。

用法：
    loader = PromptLoader()
    loader.load("prompts/")
    prompt = loader.get("todo.system_assistant")
    prompt = loader.get("rag.user_query_template", query="...", context="...")
"""

import yaml
from pathlib import Path


class PromptLoader:
    _instance = None
    _prompts: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self, prompts_dir: str | Path):
        """从目录递归加载所有 .yaml 文件，合并到 _prompts"""
        prompts_dir = Path(prompts_dir)
        if not prompts_dir.exists():
            raise FileNotFoundError(f"Prompts dir not found: {prompts_dir}")

        for yaml_file in sorted(prompts_dir.rglob("*.yaml")):
            try:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    self._prompts.update(data)
            except Exception as e:
                print(f"Warning: failed to load {yaml_file.name}: {e}")

    def get(self, key: str, **kwargs) -> str:
        """用点号路径获取 prompt，支持 {var} 替换

        Args:
            key: 点号分隔路径，如 "todo.system_assistant"
            **kwargs: 替换变量，如 query="...", context="..."

        Returns:
            格式化后的 prompt 字符串

        Raises:
            KeyError: 路径不存在
        """
        val = self._prompts
        for part in key.split("."):
            if isinstance(val, dict):
                val = val[part]
            else:
                raise KeyError(f"Cannot traverse into non-dict at '{part}' in key '{key}'")

        if not isinstance(val, str):
            raise TypeError(f"Expected string at '{key}', got {type(val).__name__}")

        return val.format(**kwargs) if kwargs else val

    def keys(self, prefix: str = "") -> list[str]:
        """列出所有可用的 prompt key"""
        def _collect(d, path=""):
            results = []
            for k, v in d.items():
                full = f"{path}.{k}" if path else k
                if isinstance(v, dict):
                    results.extend(_collect(v, full))
                elif isinstance(v, str):
                    results.append(full)
            return results

        all_keys = _collect(self._prompts)
        return [k for k in all_keys if k.startswith(prefix)] if prefix else all_keys

    def reload(self, prompts_dir: str | Path):
        """清空并重新加载"""
        self._prompts.clear()
        self.load(prompts_dir)
