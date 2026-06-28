# mineru-ocr AI 增强层设计方案

## 一、背景与动机

当前 `mineru-ocr` 将 PDF/Office 文档通过 MinerU Cloud 转为 Markdown，输出是**保留原格式的文本提取**——本质上还是给人类看的排版还原，不是给 AI 理解的语义结构。

具体短板：

| 问题 | 表现 |
|------|------|
| **图片** | 只提取了图片文件（assets/），AI 看不到内容 |
| **表格** | Markdown 表格格式保留，但 AI 需要自己推断"这个表格在说什么" |
| **语义** | 没有章节摘要、实体提取、跨文档关系 |

**目标**：在现有输出基础上，新增一个可选的 AI 增强层，输出一份 AI 友好的增强文档。

---

## 二、整体架构

```
mineru-ocr process file.pdf --enhance
                      │
            MinerU Cloud OCR
                      │
            ┌─────────┴─────────┐
            ▼                   ▼
        full.md + assets     full.md + assets
        （原始输出）              │
                            Doubao-Seed-2.0-lite
                           （火山引擎 Coding Plan）
                                │
                        1. 图片逐个分析 → 结构化语义
                        2. 全文分析 → 章节摘要/实体/关系/标签
                                │
                                ▼
                        full.enhanced.md
                    （原文 + AI 元数据块）
```

---

## 三、模型选型

| 任务 | 模型 | 来源 |
|------|------|------|
| 图片理解 | Doubao-Seed-2.0-lite | 火山引擎 Coding Plan |
| 表格理解 | Doubao-Seed-2.0-lite（同上） | 同上 |
| 全文元数据提取 | Doubao-Seed-2.0-lite（同上） | 同上 |

**只配置一个额外 API Key**，一个模型覆盖全部增强需求。

---

## 四、输出格式：full.enhanced.md

一份 Markdown 文件，包含两部分：

### 第一部分：原始全文

MinerU 原始输出的全部内容，**原样保留，不做任何修改**。

### 第二部分：AI 增强元数据块

```
---

> ## AI 增强元数据
>
> ### 章节摘要
> | 章节 | 摘要 |
> |------|------|
> | 一、XX | ... |
> | 二、XX | ... |
>
> ### 实体与术语
> | 实体 | 类型 | 说明 |
> |------|------|------|
> | ... | ... | ... |
>
> ### 跨章节关系
> - 章节 A 的 XX 内容支撑章节 B 的 XX 分析
>
> ### 标签
> `#tag1` `#tag2` `#tag3`
>
> ### 图片语义
> ````json
> [
>   {
>     "file": "assets/xxx.jpg",
>     "type": "line_chart|bar_chart|table|diagram|photo|screenshot",
>     "summary": "图片内容一句话摘要",
>     "elements": ["关键视觉元素1", "关键视觉元素2"],
>     "key_findings": ["关键发现1", "关键发现2"],
>     "keywords": ["关键词1", "关键词2"]
>   }
> ]
> ````
```

AI 元数据块使用 `>` blockquote 包裹，既与原文视觉区分，也便于程序解析。

---

## 五、环境变量配置

| 变量 | 说明 | 默认值 | 必填 |
|------|------|--------|------|
| `MINERU_API_TOKEN` | MinerU Cloud API Token | - | ✅（已有） |
| `DOUBAO_API_KEY` | 火山引擎 Coding Plan API Key | - | ✅（使用 --enhance 时） |
| `DOUBAO_BASE_URL` | 火山引擎 API Endpoint | `https://ark.cn-beijing.volces.com/api/coding/v3` | ❌ |
| `DOUBAO_MODEL` | 豆包模型名 | `doubao-seed-2.0-lite` | ❌ |

---

## 六、CLI 用法

```bash
# 不增强（默认行为，和现在完全一样）
mineru-ocr process file.pdf

# 增强输出
mineru-ocr process file.pdf --enhance

# 也可在提交后单独对已有 job 做增强（后续考虑）
mineru-ocr enhance <job_id>
```

---

## 七、新增文件清单

### 1. `src/mineru_ocr/doubao_client.py`

Doubao API 客户端，OpenAI 兼容格式调用火山引擎：

- `analyze_image(image_base64: str) → dict`：图片理解，返回结构化 JSON
- `analyze_text(markdown: str) → dict`：全文分析，返回元数据
- 重试、错误处理、Token 统计

### 2. `src/mineru_ocr/enhancer.py`

增强层核心逻辑：

- `enhance_output(output_dir: Path) → Path`：入口函数
  - 遍历 `assets/`，逐个图片调用 Doubao 分析 → 汇总
  - 读取 `full.md`，调用 Doubao 全文分析
  - 组装 `full.enhanced.md`

### 3. 修改 `src/mineru_ocr/cli.py`

- `process` 子命令新增 `--enhance` 参数
- 处理后调用 `enhance_output()`

---

## 八、关键 Prompt 设计（草案）

### 图片理解 Prompt

```
你是一个文档图片分析专家。分析这张从文档中提取的图片，输出 JSON：

{
  "type": "图片类型",
  "summary": "一句话概括图片内容",
  "elements": ["图片中的关键视觉元素列表"],
  "key_findings": ["从图片中能得出的关键结论"],
  "keywords": ["可用于检索的关键词，5-10个"]
}

图片类型可选值：line_chart（折线图）| bar_chart（柱状图）| pie_chart（饼图）| table（表格截图）| diagram（流程图/示意图）| photo（照片）| screenshot（截图）| other（其他）

仅输出 JSON，不要其他内容。
```

### 全文增强 Prompt

```
你是一个文档分析专家。分析以下文档内容，提取结构化元数据。

要求：
1. 不要修改或重写原文
2. 只提取文档中客观存在的信息
3. 如果某类信息不存在，对应字段留空

输出格式：
{
  "sections": [
    {"title": "章节标题", "summary": "该章节核心内容一句话摘要"}
  ],
  "entities": [
    {"name": "实体名称", "type": "组织/人物/地点/指标/概念", "description": "简要说明"}
  ],
  "cross_references": [
    "章节A与章节B的关系描述"
  ],
  "tags": ["标签1", "标签2"]
}
```

---

## 九、与现有代码的关系

| 现有文件 | 是否修改 | 说明 |
|---------|---------|------|
| `cli.py` | ✅ 是 | `process` 子命令加 `--enhance` 参数 |
| `service.py` | ❌ 否 | 增强在 process 完成后调用，不侵入核心流程 |
| `merge.py` | ❌ 否 | 增强在 merge 之后执行 |
| `models.py` | ❌ 否 | 不涉及数据模型变更 |
| `client.py` | ❌ 否 | MinerU API 客户端不变 |
| `planner.py` | ❌ 否 | 不变 |
| `storage.py` | ❌ 否 | 不变 |

**新增文件**：`doubao_client.py`、`enhancer.py`

---

## 十、向后兼容性

- 不加 `--enhance` 时，行为、输出、性能完全不变
- `full.md` 始终保留原始 MinerU 输出
- `full.enhanced.md` 是新增文件，不影响已有流程
- 没配 `DOUBAO_API_KEY` 时 `--enhance` 给出明确错误提示

---

## 十一、验证方式

```bash
# 验证向后兼容
mineru-ocr process test.pdf
ls test.pdf.mineru/
# 应包含: full.md  assets/  manifest.json（和现在一样）

# 验证增强输出
mineru-ocr process test.pdf --enhance
ls test.pdf.mineru/
# 应额外包含: full.enhanced.md

# 验证 AI 元数据块格式
head -5 test.pdf.mineru/full.enhanced.md   # 应为原始内容开头
tail -80 test.pdf.mineru/full.enhanced.md  # 应为 AI 元数据块
```

---

## 十二、后续可扩展方向（本次不包含）

- 多 Job 结果合并增强
- 跨文档关系链接
- 输出向量化嵌入
- Webhook 通知增强完成
