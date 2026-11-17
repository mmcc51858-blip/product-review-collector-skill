# 统一的带图 Excel 交付

默认每个商品交付一份 `.xlsx` 和原始截图 / 数据包。表头、列宽和颜色由 `assets/workbook-format.json` 固定，所有电脑和两条采集路径共用：序号、买家（匿名）、发表日期原文、购买规格原文、评论正文原文、星级原文、评论截图预览、证据文件、平台评价ID。冻结前六行及前两列，正文换行，每条评论的预览嵌入 G 列并保持比例。多屏评价预览首尾两张，H 列保留全部证据文件；不能把本地自编序号当平台评价 ID。

源数据必须包含 `reviews.json`（安卓）或 `reviews.jsonl` + `state.json` + 本次适配 JSON（CDP），以及记录引用的原始截图。单独 CSV 无法保存图片，改名为 `.xlsx` 也不能恢复图片。已有源数据和截图时直接补导出，无需重采；缺原始截图则明确缺口，只能在用户指定商品范围内补拍。

## 有 Codex 表格运行库

使用可用的 Spreadsheets 技能及其捆绑 `@oai/artifact-tool`、`sharp` 和 Node。复制本包 `scripts/` 和 `assets/` 两个目录到本次构建目录，保持相对层级，在构建目录链接环境提供的 `node_modules`。不能只复制一个 `.mjs` 导致找不到格式文件。不打包依赖、链接或写死这台电脑的用户目录。

```text
node scripts/export_reviews.mjs <安卓采集目录> <输出.xlsx>
node scripts/export_reviews.mjs <CDP采集目录> <输出.xlsx> --config <本次adapter.json>
```

导出器生成首部、中段和末尾的 QA 预览。检查预览后运行下方独立验收命令。若运行库不存在或不能加载，转到便携方案；不要因运行库缺失退化为仅交 CSV。其他采集或数据错误仍需修复，不能通过换引擎忽略错配。

部分捆绑运行库在打印 `EXPORTED`、完成保存后仍返回退出码 1。此时不能仅凭日志声称成功，也不要直接丢弃文件：用下方 `--verify-only` 检查已保存文件并查看预览，全部通过才交付。没有成功保存或验收失败仍属于导出失败。

## 其他电脑没有专用运行库

便携导出只需要 Python 3.10+，不需要 Node、Excel 安装或本机专用运行库。用任务目录的虚拟环境安装 `scripts/export-requirements.txt`，不向系统全局安装：

```text
python -m venv <任务目录>/.export-venv
<虚拟环境Python> -m pip install -r scripts/export-requirements.txt
<虚拟环境Python> scripts/export_reviews_portable.py <安卓采集目录> <输出.xlsx>
<虚拟环境Python> scripts/export_reviews_portable.py <CDP采集目录> <输出.xlsx> --config <本次adapter.json>
```

Windows 虚拟环境解释器是 `<任务目录>/.export-venv/Scripts/python.exe`；macOS / Linux 是 `<任务目录>/.export-venv/bin/python`。始终用同一解释器安装和执行。没有 Python 或依赖安装失败时，报告“Excel 尚未导出”和具体原因，保留断点，不能声称 CSV 已满足默认交付。依赖依据：[openpyxl 图片嵌入](https://openpyxl.readthedocs.io/en/stable/images.html)、[安装与 Pillow 依赖](https://openpyxl.readthedocs.io/en/stable/tutorial.html#installation)。

便携导出同样嵌入图片，并核对源数据和数量；截图缺失、任务身份不一致、字段被截断或图片未嵌入会报错。保存采用临时文件验收后替换，失败时保留已有正确 Excel。特别长的评论或大量跨屏证据超过 Excel 单行高度时需改成多行布局，不能裁掉原文后交付。

## 交付验收（两个引擎都做）

此命令仅依赖 Python 标准库，不需要安装便携导出依赖：

```text
python scripts/export_reviews_portable.py <安卓采集目录> <输出.xlsx> --verify-only
python scripts/export_reviews_portable.py <CDP采集目录> <输出.xlsx> --config <本次adapter.json> --verify-only
```

验收要通过：实际条数及所有原文字段与源数据一致、表头一致、每条有 G 列内嵌图片、图片不是外链、冻结位置正确、XLSX ZIP 完整。代码校验不能证明截图拍摄时的商品和内容归属，仍须抽查首部、中段、末尾对应的原始截图与表格。便携引擎在可用表格渲染器或 Excel / WPS 中查看样式；无法进行可视检查时明确报告实际验证范围，不声称已经验证原生客户端。

最终给用户可点击的 `.xlsx` 和原始截图 / 数据包链接，报告实际条数、排序 / 筛选、停止原因和缺口。CSV 仅作为附加备份。仅在用户明确要求纯文本或仅 CSV 时可省略 Excel。
