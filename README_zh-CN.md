# MinerU OCR

简体中文 | [English](README.md)

面向 [MinerU](https://mineru.net/) 云端 API 的长文档 OCR 编排项目，以 Python CLI 和可复用 Agent Skill 提供能力。

MinerU OCR 主要解决单次 API 请求难以稳定处理的本地长 PDF：自动规划页码范围、上传并跟踪每个分段、恢复局部失败、下载 MinerU 结果压缩包，并按照原始页序合并 Markdown 与引用资源。

> `process`、`submit` 会将文档上传至 MinerU Cloud；可选的 `enhance` 会将文档文本和引用图片发送至配置的 Doubao 服务。`publish`、`validate` 仅在本地运行，无需服务凭据。

## 0.2.0 更新特征

本版本将 OCR 结果组织为可溯源的多模态知识素材：原始 Markdown、资产与来源 manifest，以及可选的 AI 派生 JSONL。

- **发布与校验落地**：新增 `publish`、`validate` 和 `process --output-dir`，完成资源检查、引用重写与最终交付。共享资产按内容哈希存储，文档自动避让同名文件，保留原文档和结果包。
- **稳定标识与来源证据**：manifest 包含 `doc_id`、`asset_id`、源版本、文件哈希和每次资源引用的位置。兼容的 Content List V1 可映射原 PDF 页码和 bbox；定位不足时明确记录范围或未知，上游布局 JSON 保留在 `evidence/`。
- **结构化视觉理解**：可选 AI JSONL 区分图中观察和上下文推断，补充机械尺寸、流程关系、图表内容等字段；尺寸、单位、公差字符串不做换算。记录生成信息、逐图失败、不支持的格式及复核状态，并保留原生 SVG 资产。
- **内容保真与引用修复**：修复空表格单元格错列、独立数值丢失、HTML 图片关联缺失和来源范围错配。支持完整、折叠、简写及重复引用；不同分段的同名标签分别处理，避免图片串段。增强仅处理当前文档实际引用的图片。
- **长文与重试可靠性**：超长单行继续拆分，避免静默截断；模型输入片段上限为 40,000 字符，检索文本块上限为 8,000 字符。保留多点号文件名，重新增强时只原子替换对应 JSONL；下载完成后的合并失败也可恢复。
- **统一 CLI 与 Skill**：以 `mineru-ocr` 为维护入口，更新 Agent Skill 和[知识素材契约](.agents/skills/mineru-ocr/references/knowledge-materials.md)。最低 Python 版本调整为 3.11，移除旧 `mineru-ocr-mcp` 入口及 MCP 依赖。

建议先发布，再增强最终 Markdown，使 JSONL 引用与交付路径一致。AI 的 `ok` 状态仅表示结构校验通过，仍需复核，不能视为已验证的技术结论。

## 项目背景

MinerU 能够高质量解析 PDF、扫描页、表格、公式、图片及常见 Office 文档。其 API 采用异步任务模式，并对单次请求的文件大小和页数设有限制。短文档可直接调用 API，但长 PDF 还需要处理以下工程问题：

- 确定稳定、连续的页码范围；
- 避免提交超过限制的物理文件；
- 将多个异步任务视为同一文档管理；
- 仅重试失败分段；
- 按原始顺序合并 Markdown 和资源。

本项目负责这些编排工作，实际 OCR 推理仍由 MinerU 完成。它不是官方工具的替代品，而是官方 [MinerU Document Extractor Skill 与 `mineru-open-api` CLI](https://github.com/opendatalab/MinerU-Ecosystem) 在长文档场景下的补充。

## 主要能力

- **长 PDF 规划**：按连续页码每200页生成一个逻辑分段。
- **逻辑分页处理**：PDF 不超过200MB时重复上传完整源文件，由 MinerU 后台按页码范围选取内容。
- **超大 PDF 处理**：PDF 超过200MB时执行物理拆分，分片采用190MB安全阈值。
- **可恢复任务**：在本地持久化复合任务状态，仅重试失败分段。
- **有序合并**：按照原始页序合并结果，并写入不可见的来源页码标记。
- **资源链接重写**：安全解压结果 ZIP，复制资源并重写 Markdown/HTML 相对引用。
- **小型 Office 文档**：直接提交 DOC/DOCX、PPT/PPTX、XLS/XLSX。
- **CLI 接口**：既可用于终端脚本，也可通过 Agent Skill 工作流调用。
- **用户级凭据**：支持 `MINERU_API_TOKEN` 或本地明文用户配置，不将 Token 提交到仓库。

## 如何选择 MinerU 工具

| 场景 | 推荐工具 |
| --- | --- |
| 小文档、URL、图片、网页、Flash免登录模式、多格式导出 | 官方 [`mineru-open-api`](https://github.com/opendatalab/MinerU-Ecosystem/tree/main/cli/mineru-open-api) / `$mineru-document-extractor` |
| 超过200页的 PDF、超过200MB的 PDF、断点续跑、确定性合并 | 本项目 `mineru-ocr` / `$mineru-ocr` |
| OCR 后的检索、深读与知识库建设 | [MinerU Document Explorer](https://github.com/opendatalab/MinerU-Document-Explorer) |

## 架构

```text
Agent Skill / CLI
              │
              ▼
      本地规划与任务存储
    ├─ 页码范围规划
    ├─ 可选 PDF 物理拆分
    └─ 可恢复复合任务
              │
              ▼
       MinerU Cloud API v4
    ├─ 签名地址上传
    ├─ 异步解析
    └─ 结果 ZIP 下载
              │
              ▼
        安全解压与合并
    ├─ 有序 Markdown
    ├─ 重写后的资源
    └─ 来源清单
```

## 环境要求

- Python 3.11 或更高版本（本机使用现有 Python 3.12）
- 从 [MinerU API 管理页面](https://mineru.net/apiManage/docs)获取的 Token
- 能够访问 MinerU及其签名上传、下载地址的网络环境

安装时会自动引入 `httpx`、`pydantic`、`pypdf` 和 `platformdirs`。

## 安装

### 1. 克隆并安装

```bash
git clone git@github.com:sherwood-shehy/MinerU-OCR.git
cd MinerU-OCR
python -m pip install -e .
```

开发环境可安装测试依赖：

```bash
python -m pip install -e ".[test]"
```

### 2. 配置 MinerU Token

推荐使用交互配置：

```bash
mineru-ocr config set-token
mineru-ocr config show
```

Token 会以明文保存在当前操作系统的用户配置目录中，例如 Windows 的 `%LOCALAPPDATA%\mineru-ocr\config.toml`，不会写入本仓库。

也可设置环境变量：

```bash
export MINERU_API_TOKEN="your-token"       # Linux/macOS
```

```powershell
$env:MINERU_API_TOKEN = Read-Host "MinerU Token" -MaskInput
```

读取优先级：

```text
MINERU_API_TOKEN 环境变量 > 用户 config.toml
```

### 3. 安装 Agent Skill

仓库已包含 `.agents/skills/mineru-ocr`。从本仓库启动 Codex 时会自动发现该 Skill。

如需全局使用，可复制到用户 Skill 目录：

```bash
mkdir -p ~/.agents/skills
cp -R .agents/skills/mineru-ocr ~/.agents/skills/mineru-ocr
```

PowerShell：

```powershell
New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
Copy-Item -Recurse -Force ".agents\skills\mineru-ocr" "$HOME\.agents\skills\mineru-ocr"
```

重启 Codex或开启新线程后，可显式调用 `$mineru-ocr`，也可以直接描述相符的 OCR 任务。

## CLI 使用方法

### 一站式处理

```bash
mineru-ocr process "/path/to/document.pdf"
```

常用参数：

```bash
mineru-ocr process document.pdf \
  --model vlm \
  --language ch \
  --timeout 1800
```

默认使用 VLM、启用 OCR、使用中英文识别、启用表格和公式识别。

### 异步与断点续跑

```bash
# 提交并保存返回的本地 job_id
mineru-ocr submit document.pdf

# 刷新状态；全部完成后会自动下载和合并
mineru-ocr status <job-id>

# 仅重试失败分段
mineru-ocr resume <job-id> --timeout 1800

# 删除未完成任务的缓存
mineru-ocr clean <job-id>
```

### Token 管理

```bash
mineru-ocr config show
mineru-ocr config set-token
mineru-ocr config clear-token
```

`show` 只显示配置路径和生效来源，不会输出 Token。

## 处理规则

### PDF 不超过200MB

- 不在本地物理拆分源 PDF。
- 不超过200页时只上传一次。
- 更长 PDF 生成类似 `1-200`、`201-364` 的连续页码范围。
- 每个范围均上传完整源文件，由 MinerU 后台选择页面。

### PDF 超过200MB

- 启用本地物理拆分。
- 每片最多200页。
- 分片超过190MB时继续递归二分。
- 永不删除或修改原始 PDF。

### Office 文件

小型 DOC/DOCX、PPT/PPTX、XLS/XLSX 可直接提交。本项目明确不依赖 LibreOffice；如果 Office 文档超过服务限制，请先手动导出为 PDF。

## 输出

核心 CLI 在复合任务完成时，会先在源文件旁生成合并结果包：

```text
document.pdf.mineru/
├── full.md
├── assets/
│   ├── part-0001/
│   └── part-0002/
└── manifest.json
```

`publish` 命令已实现向用户指定共享目录发布结果；`process --output-dir` 会自动调用它：

- 最终以 `<源文件基名>.md` 直接发布到所选目录；
- 使用 `<源文件基名> (1).md` 等名称避让冲突，绝不覆盖；
- 资源统一整理到共享 `assets/` 并重写引用；
- 同步发布 `<源文件基名>.manifest.json`，包含稳定文档/资产 ID、资源哈希和来源定位；
- 按内容哈希整理共享资源，保留上游布局 JSON 到 `evidence/`；
- 验证最终 Markdown 和资源，保留原 `.mineru` 结果包；
- 永不删除或修改原始源文档。

```bash
# 基础材料：正文、表格、图片引用、来源清单
mineru-ocr process report.pdf --output-dir knowledge
# 进阶材料：在发布后的文件旁生成视觉理解 JSONL
mineru-ocr process report.pdf --output-dir knowledge --enhance
# 对已有结果进行纯本地发布与校验
mineru-ocr publish report.pdf.mineru --output-dir knowledge
mineru-ocr validate knowledge/report.md
```

`publish` 不迁移旧 AI JSONL。需要增强时，对发布后的 Markdown 执行 `enhance`；原结果包及其旧增强仍保留。已有文件名自动避让；重新增强只原子更新对应的 `.ai.jsonl`。详细身份、定位、视觉解释与检索约定见 [知识素材契约](.agents/skills/mineru-ocr/references/knowledge-materials.md)。

## AI 增强输出

> AI 增强层是一个**独立、可选**的后处理环节。它不影响核心 OCR 管线，通过 `--enhance` 参数按需启用。

MinerU 完成 Markdown 提取后，可选的 AI 增强层会生成一个适合检索和知识库导入的 JSONL 文件。原始 Markdown 仍是证据层，不会被修改。

### 设计背景与考虑

**为什么要做 AI 增强？** MinerU 输出的 Markdown 保留了文档的视觉布局、表格和图片，适合人阅读。但 AI 智能体消费这些输出时，如果能直接获取结构化元数据——每张图表描述什么、每个章节出现哪些实体、章节之间如何关联——就不用重新通读整份文档。

**单一模型策略。** 增强层默认由配置的 Doubao 模型承担图片和文本分析。文本按长度分片，每次调用只看到该片段；不保证一次获得全文上下文，也不保证发现跨片段关系。

**非破坏性输出。** 原始 Markdown 始终保持不变。AI 输出只写入同级 `<source>.ai.jsonl` 文件。如果原始 Markdown 已经生成，可直接运行 `mineru-ocr enhance <markdown-or-result-dir>`，不会重复 OCR。

**分片文本分析。** 长文档不再静默截断，而是按章节感知的方式分片分析。覆盖范围元数据会写入 JSONL 的第一条 metadata 记录。

**逐图错误容忍。** 单张图片损坏或无法识别不会影响其余图片和全文分析。每张图片独立处理，错误仅记录在该图片的 JSON 条目中。

**视觉证据与解释分开。** 可见文字、尺寸/单位/公差原样存储；上下文推断单独记录。每条派生记录带模型、提示词版本、源版本、资产 ID 和未复核状态。SVG 等原生资产保留引用，当前视觉接口不支持时标记 `unsupported`，不伪装成 JPEG。

**定位精度明确。** 兼容的 Content List V1 可提供准确源页码及归一化 bbox；只有分段范围时保留 `page_range`，缺失时标记 `unknown`。原生矢量重建、任意新版布局协议的精准映射不在此版本范围内。

**凭据隔离。** Doubao API Key 只通过 `mineru-ocr config set-doubao-key` 保存到本机用户配置。它不会写入仓库文件、生成的 Markdown、manifest、示例或回复。

### 架构

```text
             MinerU 输出
         full.md + assets/
                │
                ▼
  ┌─────────────────────────────┐
  │     Doubao-Seed-2.0-lite    │
  │                             │
  │  1. analyze_text(full.md)   │
  │     → 章节摘要、实体、      │
  │       关系、标签            │
  │                             │
  │  2. analyze_image(每张图片) │
  │     → 类型、概要、元素、    │
  │       发现、关键词          │
  └─────────────────────────────┘
                │
                ▼
       <source>.ai.jsonl
```

### 输出格式

增强层会在源 Markdown 旁边写出一个 AI 消费文件：

| 文件 | 用途 |
| ---- | ---- |
| `<source>.ai.jsonl` | 每行一个 metadata、文本或图片 chunk，包含归一化表格、图片解释、图片上下文、章节路径、页码和覆盖范围元数据，便于检索和智能体工作流消费。 |

### 使用方法

```bash
# 一站式：处理并增强
mineru-ocr process report.pdf --enhance

# 对已有结果重新运行增强
mineru-ocr enhance report.pdf.mineru/

# 也可以增强已发布的 Markdown 文件
mineru-ocr enhance report.md
```

### 配置参数

使用 `--enhance` 前，先在本机配置 Doubao：

```bash
mineru-ocr config set-doubao-key
# 输入：你的豆包apikey
```

默认参数是 `https://ark.cn-beijing.volces.com/api/coding/v3` 和 `doubao-seed-2.0-lite`。`mineru-ocr config show` 只显示是否已配置 key，不会打印真实 key。未配置 key 时，使用 `--enhance` 或 `enhance` 子命令会提示明确的错误信息。

### 当前边界

增强层专注于单文档元数据提取。**不包含**以下能力（有意留给 Knowhere 等上层工具）：

- 跨文档知识图谱构建
- 向量嵌入或 RAG 管线集成
- Web UI 或 Dashboard
- 文档交互式问答
- Agentic 文档检索

## 可靠性与安全

- Token 不会写入任务清单或公开工具响应。
- 公开任务摘要会移除签名上传和下载地址。
- 仅接受 HTTPS 结果下载。
- ZIP 解压拒绝绝对路径、`..` 路径穿越和符号链接。
- 尽可能通过临时文件、临时目录和原子替换完成写入。
- 失败复合任务会保留在用户缓存目录中，以便恢复。

## 测试

运行离线测试：

```bash
python -m pytest --basetemp .test-tmp -p no:cacheprovider
```

0.2.0 已在 Python 3.12.2 下通过 68 项离线测试，覆盖场景包括：

- 199/200/201/400页边界规划；
- 相同完整文件使用不同页码范围重复上传；
- 模拟超大 PDF 物理拆分；
- Office 大小限制；
- Markdown 合并顺序和资源重名隔离；
- ZIP 路径穿越保护；
- API 请求结构；
- Token 优先级及清理；
- 本地发布、文件名冲突、资源缺失、哈希校验及复制失败重试；
- 稳定 ID、源页码映射、重复引用及跨分段标签隔离；
- 表格与数值保真、文本块长度限制、当前文档图片筛选和发布后增强。

受限 Windows 环境中应保留显式 `--basetemp`，因为默认用户临时目录可能不可访问。

## 实际文档验证

0.2.0 另使用一份已有的 1,545,149 字节中文 Markdown 完成本地验收，发布后的 17 个资源引用有效。替身 AI 响应跑通增强流程，生成 251 条 JSONL 记录和 18 个模型输入片段，ID 唯一；发布仅改变资源目标路径，增强不改写发布 Markdown。该验收证明本地流程正确，不代表真实云端 OCR 或视觉模型准确率。

本流程已使用一份364页中文技术标准进行验证，按 `1-200`、`201-364` 两个逻辑范围成功完成，并生成包含156个标题、327个 HTML 表格和12个图片引用的有序合并文档。与官方 CLI 输出比较时，可见文字相似度约为99.35%；对于一个异常膨胀的表格章节，自定义合并结果的标签结构明显更紧凑。

## 项目结构

```text
.agents/skills/mineru-ocr/   Agent Skill 与 MinerU API 参考
src/mineru_ocr/              CLI、API客户端、规划、存储与合并逻辑
tests/                       离线单元测试
pyproject.toml               包元数据、依赖和命令入口
```

## 已知限制

- OCR 依赖云端服务，不是离线方案。
- 服务限制和响应格式可能变化，请以最新 [MinerU API 文档](https://mineru.net/apiManage/docs)为准。
- 大型 Office 文档不会自动拆分。
- 如果单个 PDF 页面仍超过安全上传阈值，则无法继续物理拆分。
- 不尝试在不同 OCR 分段之间进行语义修复，例如自动重建恰好跨越分段边界的表格。

## 参与贡献

欢迎提交 Issue 和范围明确的 Pull Request。行为变更应补充测试，并在提交前运行完整离线测试。

## 许可证

本项目目前尚未声明独立许可证。MinerU及其 API 的使用受其上游条款和政策约束。

## 相关链接

- [MinerU 官网](https://mineru.net/)
- [MinerU API 文档](https://mineru.net/apiManage/docs)
- [MinerU 开源仓库](https://github.com/opendatalab/MinerU)
- [MinerU Ecosystem 与官方 CLI](https://github.com/opendatalab/MinerU-Ecosystem)
