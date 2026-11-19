# MinerU OCR 安装与升级（Windows）

日常转换从业务工作空间调用已安装的 `mineru-ocr`。优先复用宿主机已有的 Python 和满足版本要求的依赖。同一 Windows 用户下，多个 Agent 可以共用一套 CLI，并从各自的技能目录加载同版本 Skill。开发仓库用于修改源码、运行测试和构建发布包。

## 获取同版本发布包

从 GitHub 下载同一版本的 wheel 和 Skill ZIP。以下使用 1.1 的文件名。 [v1.1 Release](https://github.com/sherwood-shehy/MinerU-OCR/releases/tag/v1.1)

| 发布产物 | 文件名 |
| --- | --- |
| CLI 安装包 | `mineru_ocr_skill-1.1-py3-none-any.whl` |
| 全局 skill | `mineru-ocr-skill-v1.1.zip` |

wheel 和 Skill ZIP 应从同一源码修订版本构建。若同时收到 `SHA256SUMS.txt`，可用 `Get-FileHash -Algorithm SHA256 <文件路径>` 核对下载文件。

如果需要从源码安装 1.1，在对应的源码目录运行以下命令。构建产物会写入系统临时目录中的 `mineru-ocr-v1.1` 子目录。

```powershell
$releaseDir = Join-Path $env:TEMP 'mineru-ocr-v1.1'
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
python -m pip wheel --no-deps --wheel-dir $releaseDir .
Compress-Archive -LiteralPath '.\.agents\skills\mineru-ocr' `
  -DestinationPath (Join-Path $releaseDir 'mineru-ocr-skill-v1.1.zip') -Force
```

## 安装 CLI

在 Agent 实际使用的 Windows 用户下，选定宿主机已有且允许安装第三方包的 Python 3.11 或更高版本。下面用 `$runtimePython` 指定解释器。如果 `python` 指向其他解释器，将 `$runtimePython` 设为选定的 `python.exe` 完整路径。

```powershell
$runtimePython = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
& $runtimePython --version
& $runtimePython -m mineru_ocr.cli --version
& $runtimePython -m mineru_ocr.cli doctor
```

如果 CLI 版本与 Skill 匹配，并且 `doctor` 的 `pdf_ready` 和 `local_ready` 均为 `true`，即可直接复用。需要安装或补齐依赖时，将 `$releaseDir` 改为发布包所在目录，用同一个解释器直接安装 wheel。

```powershell
$releaseDir = 'C:\path\to\mineru-ocr-v1.1'
$wheel = Join-Path $releaseDir 'mineru_ocr_skill-1.1-py3-none-any.whl'
& $runtimePython -m pip install $wheel
& $runtimePython -m mineru_ocr.cli --version
& $runtimePython -m mineru_ocr.cli doctor
```

`pip` 会复用选定解释器已能访问且符合版本要求的依赖。1.1 的必装依赖包含 PyMuPDF、PyMuPDF4LLM 和 PyMuPDF Layout，三者均为 1.28.2，支持 PDF 表格预检、自动分流、本地提取和后处理。安装后确认 `pdf_ready` 和 `local_ready` 均为 `true`。

在同一 Windows 用户下，新 CLI 会读取现有用户配置。需要使用云端 OCR 且尚未配置时，运行 `& $runtimePython -m mineru_ocr.cli config set-token` 交互式录入。`MINERU_API_TOKEN` 若已设置，优先于配置文件。`config show` 只报告配置状态，本地转换无需 token。

### 依赖冲突或安装受限时

如果共享环境已有其他版本的 PyMuPDF 系列组件，可用 `& $runtimePython -m pip install --dry-run $wheel` 查看安装计划。计划替换共享依赖时，先确认对其他项目的影响。

宿主机的安装限制或依赖冲突导致无法复用时，先查找已有的兼容环境。确实需要隔离且经用户确认后，可以用宿主机选定的 Python 创建一套由多个 Agent 共用的独立环境。随后用该环境的解释器继续验收和配置 Skill。

```powershell
$runtime = Join-Path $env:LOCALAPPDATA 'mineru-ocr-runtime'
& $runtimePython -m venv $runtime
$runtimePython = Join-Path $runtime 'Scripts\python.exe'
& $runtimePython -m pip install $wheel
& $runtimePython -m mineru_ocr.cli doctor
```

## 从业务工作空间验收

在开发仓库以外选择一个业务工作空间，用一份有文字层、结构简单的 PDF 试跑。根据文件实际名称修改下面的路径。多个文档可以写入同一个交付目录，平铺 Markdown 并共用 `images/`。

```powershell
& $runtimePython -m mineru_ocr.cli process '.\inbox\sample.pdf' --engine local `
  --output-dir '.\outputs\mineru-smoke'
```

用 `& $runtimePython -m mineru_ocr.cli validate <实际生成的Markdown路径>` 检查输出的引用，其中 Markdown 路径以 `process` 返回的结果为准。`--engine local` 禁止上传，输入若不适合本地提取，换用适合的测试文件。再确认模块的位置属于运行环境。

1.1 会在内部校验通过后清理任务临时目录。若需保留 manifest、快照、报告或原始包复核，可在转换时显式加 `--work-dir`，并在校验时传入同一路径。已发布的 v1.0 wheel 对应 [v1.0 安装文档](https://github.com/sherwood-shehy/MinerU-OCR/blob/v1.0/docs/install.md)。

```powershell
& $runtimePython -c "import mineru_ocr; print(mineru_ocr.__file__)"
```

预期路径位于所选解释器可见的 `site-packages` 安装目录。检查原件仍在 `inbox/`，过程记录和交付各自在指定目录。

## 配置全局 skill

1. 在 Agent 使用的环境中运行 `Get-Command mineru-ocr -All`，再用 `mineru-ocr doctor` 核对 `executable` 是否对应选定的 `$runtimePython`。如果命令未找到或解析到其他环境，可以由 Agent 使用选定解释器执行 `-m mineru_ocr.cli`，也可以调整该用户的 `Path`，让实际安装 CLI 的 `Scripts` 目录优先，然后重开 PowerShell 和 Agent 应用复查。
2. 将 skill ZIP 解压到临时目录。取其中的 `mineru-ocr/` 目录放入 Agent 的用户级技能目录。以本机布局为例，Codex 和 Claude 可共用 `%USERPROFILE%\.agents\skills\mineru-ocr`。如果 Claude 已有指向该目录的链接，继续沿用。已有同名 skill 时先将旧副本备份到技能搜索目录之外。完成后应能在目标目录直接找到 `SKILL.md`、`agents/` 和 `references/`。
3. 在本机 Agent 中打开业务工作空间，用全局 `mineru-ocr` skill 再运行一次转换，确认它调用的是发布版，文件写入业务工作空间指定目录。

## 升级与回退

升级前保留当前 wheel 和配套 Skill ZIP。用同一个 `$runtimePython` 安装目标版本的 wheel，再替换全局 Skill 副本。如果安装计划涉及替换共享依赖，按上面的冲突处理方式确认。切换后重新检查命令版本、`doctor` 和业务目录中的本地转换。回退时，按目标版本的安装说明装回配套的 wheel 和 Skill ZIP。安装与回退沿用用户 token 配置。
