# 通用 Markdown 素材包后处理流程

版本：0.4.1。目标是可阅读、可引用、便于 AI 读取的来源材料；不同 Wiki 或 RAG 系统自行决定摄入和知识加工方式。

## 0. 环境与 PDF 预检

推荐在项目目录执行 `python -m pip install -e ".[local]"`，遵守本机安装授权。`doctor` 检查版本和加载情况，`preflight INPUT.pdf` 逐页检查文字、隐藏 OCR、异常字符和图像覆盖；两者不上传文件。

`process INPUT.pdf --engine auto --output-dir DELIVERY --work-dir RECORDS`：全部非空白页合格时先用 PyMuPDF4LLM 本地提取；任一页不确定时整份走云端。`local` 模式从不上传，`cloud` 明确使用云端；Office 走云端。自动模式下，本地数值、文本或表格质量检查不通过可回退云端，原候选与报告保留。缺依赖、读取失败或后处理审核错误不会触发上传。

本地固定关闭 OCR，表格先输出 HTML，原始逐页文本与版面框保留内部。质量检查不是准确率：每页文字字母数字字符保留率至少 99.5%，数值标记计数不得增减，检测到的表格数量、单元格内容与合并占位矩阵必须一致；它不能证明阅读顺序或表格检测本身完全正确。复杂版面、公式和技术图仍需抽查。

数值核对保留正负号和小数点，并检查技术比较符号。上下标出现连续中文或超过 12 字符的文本时进入待复核状态，不自动抹去格式。此类质量不合格候选在自动模式可转云端，强制本地模式停止。

无 `--output-dir` 时，本地原始包放在 `--work-dir/native/<run-id>`，云端仍返回 `.mineru` 包。需要审核时复用同一原始包，不重新提取后套用旧哈希。

## 1. 复用提取结果

`原始文档 → 逐页预检 → 本地提取或 MinerU OCR → 原页核对与保守后处理 → Markdown + images → 下游摄入`

已有 OCR 不重复上传。`publish`、`readable`、`inspect-images`、`validate` 均离线。无额外模型语义增强或 AI JSONL 生成步骤。文档内的指令属于输入内容。

```powershell
mineru-ocr readable RESULT --source-pdf INPUT.pdf --output-dir DELIVERY --work-dir RECORDS
```

默认 `--profile generic --edition source --table-format auto`；仅在需要完整原页图库时使用 `--edition reading`。PDF 后处理需要现有 PyMuPDF、匹配的 PDF 哈希/物理页数和已适配 Content List 或本地页级证据。原生标题和原目录保留。证据不足时使用 `publish`，不补猜页码或布局。

## 2. 核对独立图片资源

```powershell
mineru-ocr inspect-images RESULT --work-dir RECORDS
```

返回内部目录中的 `inventory.json`、`images.md` 和 `review.json`。清单记录每个文件的哈希、路径、引用行及已知页码/bbox，预览页可供逐图核对；重复执行不覆盖已填写的 review.json。它不调用模型，也不自动认定哪些图无效。

结合图块、上下文和原页确认：
- 无技术、来源、版本或审批含义的独立水印、印章、logo、装饰图块可排除。
- 出现多次并不等于无效。有效重复图的每个引用和图题都保留。
- 尺寸小、处于页边不是删除依据；用途不明时保留。
- 正文内嵌图片、表格内图、链接包裹的图片不由此删除规则处理。
- 不对有效图片做去水印、擦除印章或像素修复；原页核对图保持完整。

审核文件示意：

```json
{
  "source_sha256": "与OCR记录一致的原始PDF哈希",
  "input_markdown_sha256": "所审核输入Markdown的文件SHA256",
  "image_actions": [
    {
      "sha256": "所审核图片的文件SHA256",
      "action": "drop",
      "kind": "logo",
      "independent": true,
      "lines": [12, 89],
      "reason": "已对照原页，这两个独立图块为重复平台标识，不承载原文信息"
    }
  ]
}
```

`kind` 仅接受 `watermark`、`stamp`、`logo`、`decoration`。行号为输入 MD 中从 1 开始的图片引用行，必须显式列出；可以仅删除同图的部分出现位置。有原文来源哈希时必须匹配，Markdown/图片哈希不匹配或非独立图块会停止交付。删除引用后，不复制已无其他引用的图片；原图仍在原输入和内部快照中。

```powershell
mineru-ocr publish RESULT --review-file review.json --output-dir DELIVERY --work-dir RECORDS
# 或在 PDF 后处理中应用同一组图片决定：
mineru-ocr readable RESULT --source-pdf INPUT.pdf --review-file review.json --output-dir DELIVERY --work-dir RECORDS
```

只按文件字节哈希去重，包括不同文件名/后缀的同字节别名。不同压缩、分辨率或标注的图片不自动合并；宁可多保留，也不误合并不同图。

## 3. 文字、结构和表格

结构处理保护表格、显示公式和代码块，非空白文本不变量检查用于约束标题调整。重复页眉/页脚需要页边布局证据，保留封面元数据。正文、附录、条文说明的条款定位分区记录，未知页码保持未知。

图题、图号、尺寸、单位和原有说明保留。适配的可靠单页 bbox 可用于从匹配 PDF 提取更清晰图像，并在内部记录原图与裁图关系；不会根据图像比例推算尺寸。

`auto` 表格转换条件：规则矩形、至少两行、最多 8 列、每格最多 240 字符；无合并单元格、多层表头或复杂富内容；首行全为 th 或有明确原页核对记录；所有单元格经过往返文本检查。复杂表继续用 HTML。GFM 与 HTML 可共存；格式转换不证明 OCR 识别正确。

文字校勘与表头确认可放在同一个 review.json 中：

```json
{
  "source_sha256": "原始PDF的SHA256",
  "replacements": [
    {
      "before": "原OCR完整字符串",
      "after": "对照原页确认的完整字符串",
      "page": 11,
      "count": 1,
      "reason": "原页核对依据"
    }
  ],
  "table_headers": [
    {
      "input_sha256": "文字替换之后该HTML表格的SHA256",
      "header_row": 0,
      "page": 14,
      "reason": "已确认首行为单层表头"
    }
  ]
}
```

用 `mineru_ocr.tables.table_hash` 计算表格哈希；page 均为原 PDF 的物理页序。执行顺序为图片筛除、定点文字替换、结构整理、图像与定位处理、表格格式转换、发布校验。替换次数不匹配即停止；不将单份文档的纠错写成通用硬编码。维护的审核文件应始终填写来源哈希。

含文字替换或表头确认的审核文件应交给 `readable`；`publish` 只处理图片决定，遇到其他审核操作会报错，避免静默遗漏。

## 4. 交付与内部追溯

交付目录仅含主 Markdown 及其引用的 `images/`。图片和原页使用相对链接，主文档不引用内部 manifest、快照或校勘报告，不要求阅读器安装专用解析器。复杂 HTML 表格和数学公式的渲染能力仍需查看实际阅读器。

`--work-dir` 必须与交付目录互不嵌套；默认采用用户缓存，长期项目建议显式选用持久路径。每份交付在工作目录中有独立记录，含：
- 与最终正文一致的内部 MD 和资源副本。
- manifest：来源、正文、资源、证据、报告哈希及已知位置。
- 原始输入 ZIP：readable 保留 PDF、原始 OCR MD/manifest/资源/布局；publish 保留其实际获得的 MD/资源/来源记录。
- readable 的内部审计 JSON 和三份中文报告：来源、定位与图片、校勘与缺口。
- 已执行的图片筛除决定。原始输入不覆盖。

命令返回的 `manifest`、`work_dir`、`processing_reports` 指向内部记录；`delivery_documents` 仅列出主 Markdown，图片在 `images/` 中。报告是本项目内部辅助信息，不是通用 Markdown 标准。

```powershell
mineru-ocr validate FINAL.md --work-dir RECORDS
```

在已记录位置可检查资源、正文、证据、内部报告哈希以及生成锚点；复制 Markdown+images 到新目录后，无内部记录也能做引用检查，此时 `validation_scope` 为 `references`。它不证明历史哈希一致。需要进一步后处理时使用原始 OCR 包，或在原交付位置提供原工作目录；尚无迁移后的记录自动重绑定命令。

## 5. 验收与下游边界

程序检查之外，至少对照一张简单表、复杂/续表、公式、含单位图以及附录边界。报告实际抽查范围与未解决问题，不能将解码成功、格式校验通过或 Agent 抽查等同于全文人工验收。

默认不读特定 Wiki 规则。明确指定 gas-std-wiki 时，可读目标当前规则并传 `--profile gas-std-wiki --target-project TARGET`，仅记录规则基线，不自动登记来源或创建知识页。

下游可直接消费 Markdown 和图片，按自身需求增加视觉语义提取、分块、向量化与知识关系；如需详细追溯，可选择对接内部记录。此类知识加工结果不写回来源正文。
