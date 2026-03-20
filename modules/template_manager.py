"""子Agent指令模板管理器

封装 PromptLoader，提供 get_template(task_type, **kwargs) 方法。
自动拼接 system + constraints + user，返回完整的子Agent指令字符串。

用法：
    from template_manager import TemplateManager
    
    mgr = TemplateManager()
    prompt = mgr.get_template("coding", 
        task_description="实现XX功能",
        requirements="1. ...\n2. ...",
        modify_files="/path/to/file.py",
        reference_files="/path/to/ref.py",
        constraints_text="不要删除现有代码",
        verification="所有测试通过",
        test_command="python -m pytest"
    )
"""

from __future__ import annotations

import yaml
from pathlib import Path


TEMPLATES_DIR = Path(__file__).parent.parent / "agent-templates" / "templates"

# Valid task types (correspond to YAML filenames without extension)
VALID_TYPES = {"coding", "research", "skill", "doc", "compress", "critic"}


class TemplateManager:
    """管理子Agent指令模板的加载和渲染"""

    def __init__(self, templates_dir: str | Path | None = None):
        self._templates_dir = Path(templates_dir) if templates_dir else TEMPLATES_DIR
        self._cache: dict[str, dict] = {}

    def _load(self, task_type: str) -> dict:
        """加载并缓存单个模板"""
        if task_type in self._cache:
            return self._cache[task_type]

        if task_type not in VALID_TYPES:
            raise ValueError(
                f"Unknown task type '{task_type}'. Valid types: {sorted(VALID_TYPES)}"
            )

        yaml_path = self._templates_dir / f"{task_type}.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError(f"Template not found: {yaml_path}")

        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Invalid template format in {yaml_path}")

        self._cache[task_type] = data
        return data

    def get_template(self, task_type: str, **kwargs) -> str:
        """获取完整的子Agent指令字符串

        Args:
            task_type: 模板类型 (coding/research/skill/doc/compress/critic)
            **kwargs: 模板变量替换

        Returns:
            拼接好的完整指令字符串: system + constraints + user
        """
        tpl = self._load(task_type)

        parts = []

        # 1. System prompt
        system = tpl.get("system", "")
        if system:
            parts.append(system.strip())

        # 2. Constraints
        constraints = tpl.get("constraints", [])
        if constraints:
            lines = ["⚠️ 约束条件："]
            for c in constraints:
                lines.append(f"- {c}")
            parts.append("\n".join(lines))

        # 3. User prompt with variable substitution
        user = tpl.get("user", "")
        if user:
            try:
                rendered = user.format(**kwargs) if kwargs else user
            except KeyError as e:
                raise KeyError(
                    f"Missing template variable {e} for task type '{task_type}'. "
                    f"Provide it as a keyword argument."
                )
            parts.append(rendered.strip())

        return "\n\n".join(parts)

    def list_types(self) -> list[str]:
        """列出所有可用的模板类型"""
        return sorted(VALID_TYPES)

    def get_variables(self, task_type: str) -> list[str]:
        """获取模板中需要的变量名列表"""
        tpl = self._load(task_type)
        user = tpl.get("user", "")
        import re
        # Match {var} but not {{var}} (escaped braces)
        # First remove escaped braces
        cleaned = user.replace("{{", "").replace("}}", "")
        return re.findall(r"\{(\w+)\}", cleaned)

    def reload(self):
        """清空缓存，强制重新加载"""
        self._cache.clear()
