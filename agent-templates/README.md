# 子 Agent 指令模板库

## 使用说明
根据任务类型选择模板，填入具体参数后派发。关键信息永远放最前面。

## 核心原则

### SAGE 四角色机制（复杂任务必用）
对于复杂任务，采用 SAGE 启发的角色分工：

| 角色 | 职责 | 何时使用 |
|------|------|---------|
| **Solver** | 执行任务 | 所有任务 |
| **Critic** | 评估输出质量 | 代码开发、重要文档 |
| **Planner** | 拆分复杂任务 | 多步骤任务 |
| **Challenger** | 生成测试用例 | 代码开发 |

**Critic Agent 模板**（在 Solver 完成后派发）：
```
你是质量审查 Agent（Critic）。任务：评估以下工作成果的质量。

## 原始任务要求
{original_task}

## 工作成果
{solver_output_path}

## 评估维度
1. **完整性**：是否完成了所有要求？遗漏了什么？
2. **正确性**：逻辑是否正确？有无 bug？
3. **安全性**：有无副作用、安全隐患？
4. **效率**：有无冗余或低效实现？
5. **可维护性**：代码/文档是否清晰易懂？

## 输出格式
{
  "score": 1-10,
  "passed": true/false,
  "issues": ["问题1", "问题2"],
  "suggestions": ["建议1", "建议2"],
  "verdict": "通过/需修改/拒绝"
}

将评估结果写入 {output_path}
```

### Lore 决策记录格式
每次做重要决策时，用以下格式记录到结构化数据库：

```bash
cd <workspace>/memory/structured
python3 memory_db.py decision \
  "决策标题" \
  "选择了什么方案" \
  "拒绝了什么替代方案" \
  "为什么这么选"
```

或在会话结束时批量记录：
```python
from memory_db import add_decision, add_observation, add_session_summary

add_decision('标题', '决策', 
    rejected_alternatives=['方案B', '方案C'],
    rationale='原因')

add_observation('discovery', '标题', 
    narrative='描述',
    facts=['事实1'],
    concepts=['概念1'])

add_session_summary('用户请求', 
    learned='学到了什么',
    completed='完成了什么',
    next_steps='下一步')
```

---

## 模板

### 1. 代码开发任务
```
⚠️ 关键约束（必须遵守）：
- [列出绝对不能做的事]
- [列出已知的坑]

## 任务
[一句话描述目标]

## 具体要求
1. [步骤1]
2. [步骤2]

## 文件路径
- 修改: [具体文件路径]
- 参考: [具体文件路径]

## 验证标准
- [怎么算完成]
- 运行测试命令: [具体命令]
```

### 2. 信息搜索/整理任务
```
## 任务
搜索/整理 [主题]

## 输出要求
- 格式: [markdown/json/表格]
- 保存到: [具体路径]
- 最少条数: 20 条
- 字段: [需要哪些信息]

## 搜索范围
- [具体的搜索源和关键词]
- 每个源至少搜集 [N] 条

## 质量要求
- [去重/验证/排序规则]
```

### 3. Skill 创建任务
```
⚠️ 关键约束：
- 严格遵循 AgentSkills 规范
- SKILL.md 必须包含 description、usage、constraints

## 任务
创建 [skill名称] skill

## 功能描述
[这个 skill 做什么]

## 目录结构
~/.openclaw/skills/[name]/
├── SKILL.md
├── scripts/  (如需要)
└── references/  (如需要)

## 参考
- 现有 skill 示例: [路径]
```

### 4. 文档/飞书操作任务
```
## 任务
[创建/更新/整理] 飞书 [文档类型]

## 目标文档
- URL/token: [具体值]
- 文件夹: [如果是新建]

## 内容要求
[具体内容描述]

## 格式要求
[排版/样式要求]
```

### 5. 记忆压缩任务（新增）
```
你是记忆压缩 Agent。任务：从以下日志文件中提取结构化信息。

日志内容：
{file_content}

请提取以下信息，以 JSON 格式输出：

{
  "observations": [
    {"type": "discovery|bugfix|decision|feature|refactor|change", "title": "简短标题", "narrative": "描述", "facts": ["事实"], "concepts": ["概念"]}
  ],
  "decisions": [
    {"title": "标题", "decision": "决策", "rejected_alternatives": ["替代方案"], "rationale": "原因"}
  ],
  "summary": "一句话总结这天发生了什么"
}

规则：
- 只提取有长期价值的信息，忽略临时调试日志
- decision 类型用于重要的架构/策略决策
- bugfix 用于踩坑和教训
- discovery 用于新发现的知识
- 每条 title 不超过 20 字
- narrative 不超过 100 字

将 JSON 输出写入 {output_path}
```

### 6. Critic 审查任务（新增）
```
你是质量审查 Agent（Critic）。

## 原始任务
{original_task}

## 成果位置
{output_path}

## 审查清单
- [ ] 完成了所有要求
- [ ] 没有违反约束
- [ ] 输出格式正确
- [ ] 无安全隐患
- [ ] 无冗余代码
- [ ] 边界情况已处理

## 输出
评分 1-10，列出问题和建议。写入 {review_path}
```

---

## 经验总结

### 指令质量
- 关键信息放最前面，用 ⚠️ 标注
- 给具体文件路径，不要让子 Agent 自己找
- 明确列出"不要做什么"（负面清单比正面清单更有效）
- 一个子 Agent 只做一件事
- 复杂任务拆成多个子 Agent，按文件分工

### 质量控制（借鉴 superpowers + SAGE）

**任务粒度**
- 每个子 Agent 任务控制在 2-5 分钟可完成的粒度
- 粒度越小，失败成本越低，成功率越高
- 大任务必须拆分，宁可多派几个子 Agent

**双阶段 Review**
子 Agent 完成后，按两个阶段审查：

阶段 1 — Spec 合规检查：
- 是否完成了指令中要求的所有事项
- 是否违反了"不要做什么"清单
- 输出格式是否符合要求

阶段 2 — 质量检查（派 Critic Agent）：
- 代码是否有副作用或安全隐患
- 是否破坏现有功能
- 是否有冗余或低效实现
- 边界情况是否处理

**TDD 优先**
代码开发任务中，要求子 Agent：
1. 先写测试（描述期望行为）
2. 运行测试确认失败（RED）
3. 写最小实现让测试通过（GREEN）
4. 重构优化（REFACTOR）
5. 不写测试的代码不予接受

### 会话结束时
每次重要会话结束前，记录到结构化数据库：
```bash
cd <workspace>/memory/structured
python3 memory_db.py add discovery "标题" "描述"
python3 memory_db.py decision "标题" "决策" "拒绝方案" "原因"
```
