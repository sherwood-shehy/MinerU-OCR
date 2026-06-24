# MinerU OCR

简体中文 | [English](README.md)

面向 [MinerU](https://mineru.net/) 云端 API 的长文档 OCR 编排项目，以 Python CLI、MCP Server 和可复用 Agent Skill 三种形式提供能力。

MinerU OCR 主要解决单次 API 请求难以稳定处理的本地长 PDF：自动规划页码范围、上传并跟踪每个分段、恢复局部失败、下载 MinerU 结果压缩包，并按照原始页序合并 Markdown 与引用资源。

> 本项目会将指定文档上传至 MinerU Cloud。必须完全离线保存的数据不应使用本项目处理。

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
- **CLI 与 MCP**：既可用于终端脚本，也可作为 Agent 的结构化工具。
- **用户级凭据**：支持 `MINERU_API_TOKEN` 或本地明文用户配置，不将 Token 提交到仓库。

## 如何选择 MinerU 工具

| 场景 | 推荐工具 |
| --- | --- |
| 小文档、URL、图片、网页、Flash免登录模式、多格式导出 | 官方 [`mineru-open-api`](https://github.com/opendatalab/MinerU-Ecosystem/tree/main/cli/mineru-open-api) / `$mineru-document-extractor` |
| 超过200页的 PDF、超过200MB的 PDF、断点续跑、确定性合并 | 本项目 `mineru-ocr` / `$mineru-ocr` |
| OCR 后的检索、深读与知识库建设 | [MinerU Document Explorer](https://github.com/opendatalab/MinerU-Document-Explorer) |

## 架构

```text
Agent Skill / MCP 工具 / CLI
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

- Python 3.10 或更高版本
- 从 [MinerU API 管理页面](https://mineru.net/apiManage/docs)获取的 Token
- 能够访问 MinerU及其签名上传、下载地址的网络环境

安装时会自动引入 `httpx`、`pydantic`、`pypdf`、`platformdirs` 和 Python MCP SDK。

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

## MCP Server

MCP Server 提供五个工具：

- `ocr_process`
- `ocr_submit`
- `ocr_status`
- `ocr_resume`
- `ocr_clean`

使用 stdio 启动：

```bash
mineru-ocr-mcp
```

Codex 的 `~/.codex/config.toml` 配置示例：

```toml
[mcp_servers.mineru_ocr]
command = "mineru-ocr-mcp"
args = ["--transport", "stdio"]
tool_timeout_sec = 1900
```

也可启动仅监听本机的 Streamable HTTP 服务：

```bash
mineru-ocr-mcp --transport streamable-http --port 8182
```

默认绑定 `127.0.0.1`。

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

Agent Skill 还规定了向用户指定共享目录发布结果的后处理策略：

- 最终以 `<源文件基名>.md` 直接发布到所选目录；
- 使用 `<源文件基名> (1).md` 等名称避让冲突，绝不覆盖；
- 资源统一整理到共享 `assets/` 并重写引用；
- 可选发布 `<源文件基名>.manifest.json`；
- 验证最终 Markdown 和资源后再删除临时 `.mineru` 结果包；
- 永不删除或修改原始源文档。

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

覆盖场景包括：

- 199/200/201/400页边界规划；
- 相同完整文件使用不同页码范围重复上传；
- 模拟超大 PDF 物理拆分；
- Office 大小限制；
- Markdown 合并顺序和资源重名隔离；
- ZIP 路径穿越保护；
- API 请求结构；
- Token 优先级及清理。

受限 Windows 环境中应保留显式 `--basetemp`，因为默认用户临时目录可能不可访问。

## 实际文档验证

本流程已使用一份364页中文技术标准进行验证，按 `1-200`、`201-364` 两个逻辑范围成功完成，并生成包含156个标题、327个 HTML 表格和12个图片引用的有序合并文档。与官方 CLI 输出比较时，可见文字相似度约为99.35%；对于一个异常膨胀的表格章节，自定义合并结果的标签结构明显更紧凑。

## 项目结构

```text
.agents/skills/mineru-ocr/   Agent Skill 与 MinerU API 参考
src/mineru_ocr/              CLI、MCP、API客户端、规划、存储与合并逻辑
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
- [Model Context Protocol](https://modelcontextprotocol.io/)
