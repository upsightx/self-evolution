# 融资动态 — 差异配置

**源标识**: `financing`
**源名称**: 融资动态
**特有指标**: 轮次 | 金额 | 投资方

## 数据源与抓取

1. 用 `exec` 调用 36kr PitchHub API 获取最新融资事件（3 页共 60 条）：
   ```bash
   curl -X POST "https://gateway.36kr.com/api/pms/project/financing/list" \
     -H "Content-Type: application/json" \
     -H "Origin: https://pitchhub.36kr.com" \
     -d '{"partner_id":"web","timestamp":'$(date +%s000)',"partner_version":"1.0.0","param":{"pageNo":"1","pageSize":"20"}}'
   ```

2. 用 `web_search` 补充：
   - "AI 融资 2026" 最近一周
   - "机器人 融资 2026" 最近一周
   - "半导体 融资 2026" 最近一周

3. 用 `web_fetch` 抓取 `https://36kr.com/newsflashes` 获取快讯中的融资信息

## 提取字段

项目名、公司全称、融资轮次、金额、投资方、行业、一句话介绍

## 特有标注

- 🔥 金额 > 1 亿人民币
- 🤖 AI 相关赛道
- 🏭 硬科技/先进制造

## 输出格式示例

```
### 1. [项目名](url) | 分数: 8.5 | 🔥 B轮 | 1.5亿人民币
- **摘要**: 公司/产品简介
- **标签**: [AI] [硬科技]
- **投资方**: 红杉中国、xxx
- **为什么值得记**: 价值说明
```
