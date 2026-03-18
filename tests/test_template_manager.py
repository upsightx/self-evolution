"""单元测试：template_manager.py

验证：
- 所有6个模板都能加载
- 变量替换正常工作
- get_template 返回完整指令（包含 system + constraints + user）
"""

import unittest
import sys
from pathlib import Path

# Ensure the module is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "modules"))

from template_manager import TemplateManager, VALID_TYPES


class TestTemplateManager(unittest.TestCase):

    def setUp(self):
        self.mgr = TemplateManager()

    def test_all_six_templates_loadable(self):
        """所有6个模板都能加载，不报错"""
        for task_type in VALID_TYPES:
            tpl = self.mgr._load(task_type)
            self.assertIn("system", tpl, f"{task_type} missing 'system'")
            self.assertIn("user", tpl, f"{task_type} missing 'user'")
            self.assertIn("constraints", tpl, f"{task_type} missing 'constraints'")
            self.assertIsInstance(tpl["system"], str)
            self.assertIsInstance(tpl["user"], str)
            self.assertIsInstance(tpl["constraints"], list)

    def test_list_types(self):
        """list_types 返回所有6种类型"""
        types = self.mgr.list_types()
        self.assertEqual(len(types), 6)
        for t in ["coding", "research", "skill", "doc", "compress", "critic"]:
            self.assertIn(t, types)

    def test_invalid_type_raises(self):
        """无效类型抛出 ValueError"""
        with self.assertRaises(ValueError):
            self.mgr.get_template("nonexistent")

    def test_coding_variable_substitution(self):
        """coding 模板变量替换正常"""
        result = self.mgr.get_template(
            "coding",
            task="实现用户登录功能",
            files="/src/auth.py",
            test_command="python -m pytest tests/",
        )
        self.assertIn("实现用户登录功能", result)
        self.assertIn("/src/auth.py", result)
        self.assertIn("python -m pytest tests/", result)

    def test_research_variable_substitution(self):
        """research 模板变量替换正常"""
        result = self.mgr.get_template(
            "research",
            topic="AI Agent 框架",
            output_format="markdown",
            output_path="/tmp/research.md",
            min_count="20",
            fields="名称, 链接, 简介",
            search_scope="GitHub + Google",
            quality_rules="按 star 数排序",
        )
        self.assertIn("AI Agent 框架", result)
        self.assertIn("/tmp/research.md", result)

    def test_compress_variable_substitution(self):
        """compress 模板变量替换正常，双花括号不被替换"""
        result = self.mgr.get_template(
            "compress",
            file_content="今天部署了新版本...",
            output_path="/tmp/compressed.json",
        )
        self.assertIn("今天部署了新版本...", result)
        self.assertIn("/tmp/compressed.json", result)
        # 双花括号应渲染为单花括号（JSON 模板）
        self.assertIn('"observations"', result)

    def test_critic_variable_substitution(self):
        """critic 模板变量替换正常"""
        result = self.mgr.get_template(
            "critic",
            original_task="实现缓存模块",
            output_path="/src/cache.py",
            review_path="/tmp/review.json",
        )
        self.assertIn("实现缓存模块", result)
        self.assertIn("/src/cache.py", result)
        self.assertIn("/tmp/review.json", result)

    def test_skill_variable_substitution(self):
        """skill 模板变量替换正常"""
        result = self.mgr.get_template(
            "skill",
            skill_name="weather",
            skill_description="获取天气信息",
            skill_path="~/.openclaw/skills/weather/",
            reference_skill="~/.openclaw/skills/github/",
        )
        self.assertIn("weather", result)
        self.assertIn("获取天气信息", result)

    def test_doc_variable_substitution(self):
        """doc 模板变量替换正常"""
        result = self.mgr.get_template(
            "doc",
            action="创建",
            doc_type="文档",
            doc_token="doccnXXXX",
            folder_token="fldcnYYYY",
            content_requirements="写一份项目总结",
            format_requirements="使用标题+列表格式",
        )
        self.assertIn("创建", result)
        self.assertIn("doccnXXXX", result)

    def test_get_template_contains_all_sections(self):
        """get_template 返回的指令包含 system + constraints + user 三部分"""
        result = self.mgr.get_template(
            "critic",
            original_task="测试任务",
            output_path="/tmp/out",
            review_path="/tmp/review",
        )
        # system 部分
        self.assertIn("质量审查 Agent", result)
        # constraints 部分
        self.assertIn("⚠️ 约束条件", result)
        self.assertIn("评估必须客观", result)
        # user 部分
        self.assertIn("测试任务", result)

    def test_missing_variable_raises(self):
        """缺少必要变量时抛出 KeyError"""
        with self.assertRaises(KeyError):
            self.mgr.get_template("coding", task_description="test")
            # coding 需要更多变量

    def test_get_variables(self):
        """get_variables 能正确提取变量名"""
        vars = self.mgr.get_variables("critic")
        self.assertIn("original_task", vars)
        self.assertIn("output_path", vars)
        self.assertIn("review_path", vars)

    def test_reload_clears_cache(self):
        """reload 清空缓存"""
        self.mgr._load("coding")
        self.assertIn("coding", self.mgr._cache)
        self.mgr.reload()
        self.assertEqual(len(self.mgr._cache), 0)


if __name__ == "__main__":
    unittest.main()
