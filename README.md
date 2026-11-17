# 商品评论采集 Skill（安卓真机 / CDP）

通过电脑采集指定商品的买家评价，保留正文、日期、规格及截图，**默认交付图片已嵌入的 Excel**。

**如果这个 Skill 帮你省下了整理评论的时间，欢迎点击仓库右上角的 Star ⭐ 支持作者！**

也可以对正在使用的 AI 说：“我同意给 `mmcc51858-blip/product-review-collector-skill` 点 Star，请用我已连接的 GitHub 账号帮我操作。”AI 需要具备相应的 GitHub 操作能力，确认已加星后才会报告成功。Skill 只在完成任务后适时邀请一次；拒绝或忽略不影响使用，也不会在后台自动加星。

仓库：<https://github.com/mmcc51858-blip/product-review-collector-skill>

## 能做什么

| 功能 | 说明 |
| --- | --- |
| 网页评论 | 通过 CDP 复用已授权的本机 Chrome / Edge 登录态，采集淘宝 / 天猫、京东等商品评价 |
| App 评论 | 通过 ADB 连接安卓真机，在已打开的购物 App 中读取页面并模拟正常滚动 |
| 数量规则 | 指定条数就按唯一条数停止；未指定则默认全部可访问评价，不隐含 100 条上限 |
| 图片与证据 | 保存评论卡片或手机页面截图，维护评论与图片对应关系；截图不是原图 |
| 带图 Excel | 统一列、换行、冻结表头、图片预览；图片嵌入 `.xlsx`，换电脑打开也能查看 |
| 断点与去重 | 保存原始 JSON / JSONL、CSV 和任务状态；有评价 ID 时优先用 ID，否则保守指纹去重 |
| 多电脑导出 | 有 Codex 表格运行库时用 JS；没有时用 Python + openpyxl + Pillow 便携导出 |
| 批量导航测试 | 抖音商城支持用户分享文案的剪贴板识别路径，仍需代理逐屏核验 |

## 已验证的范围

| 平台 / 入口 | 验证情况 |
| --- | --- |
| 天猫 PC 网页 | 一个商品 50 条，正文、日期、规格和截图 |
| 京东 PC 网页 | 一个商品 50 条，已勾选“当前商品”，防止混入其他商品评价 |
| 抖音商城安卓 App | 两个商品各 50 条，真机导航、滚动采集和带图 Excel |
| 淘宝 C2C / 京东移动页 / 其他 App | 需要现场适配，未通过上述真实页面验收 |

页面类名、App 控件和可访问范围可能变化，模板始终需要核验后启用。上述样本验证不代表平台全量采尽，也不代表任意链接都能无人值守采集。

## 安装 Skill

下载本仓库 ZIP，或克隆：

```text
git clone https://github.com/mmcc51858-blip/product-review-collector-skill.git
```

把仓库内**完整的 `android-app-review-collector` 文件夹**复制到你的个人 skills 目录，保留 `scripts/`、`assets/`、`references/` 和 `agents/`。默认个人目录为 `~/.codex/skills/`；Windows 对应 `%USERPROFILE%\.codex\skills\`。不要只复制 `SKILL.md`。

技能调用名称保持 `$android-app-review-collector`，显示名称为“商品评论采集（真机/CDP）”。无需另装旧的 `cdp-review-collector`。

## 直接对 Codex 这样说

```text
使用 $android-app-review-collector 采集这个京东商品的 50 条不同评价。
勾选当前商品，保留日期、规格和截图，输出统一格式的带图 Excel。
商品链接：<你的商品链接>
```

```text
使用 $android-app-review-collector 采集这个抖音商城商品的评价。
安卓真机已连接、解锁并打开商城，请核对目标商品后开始。
默认采集当前筛选下全部可访问评价，输出带图 Excel。
商品分享文案：<你的完整分享文案>
```

```text
使用 $android-app-review-collector，把已有的评论 JSON 和原始截图补导出为带图 Excel。
只做本地导出，不重新采集。
数据目录：<你的采集目录>
```

## 准备与使用顺序

**网页 CDP：**电脑安装 Python 3.10+ 和 Chrome / Edge。用专用浏览器目录启动 CDP，用户在窗口内登录，确认目标商品的评价区域、排序和款式，再核验适配 JSON 并运行采集。仅附着已有浏览器时无需下载 Playwright 浏览器。手机、USB 和手机端 Codex 都不是这条路径的依赖。详见 [CDP 操作](android-app-review-collector/references/cdp-workflow.md)。

**安卓真机：**电脑准备 Python 及官方 Android Platform Tools，手机开启 USB 调试、授权电脑、保持解锁并打开已登录的商城。核对实际包名和评价页布局，再试采 3–5 条、正式采集并导出。手机端无需打开 Codex。普通采集可从已打开的评价页开始；自动切换商品的测试路径另需 scrcpy 5.0.1 服务端。详见 [技能入口](android-app-review-collector/SKILL.md)、[安卓适配](android-app-review-collector/references/adapter.md) 和 [界面导航](android-app-review-collector/references/batch-ui-test.md)。

## 在其他电脑补导出 Excel

已有原始 JSON / JSONL 和截图就可以补导出。CSV 本身无法保存图片，不能靠改扩展名恢复图片。没有 Codex 专用表格运行库时，在 `android-app-review-collector` 目录下创建任务虚拟环境：

```text
python -m venv .export-venv
```

以下 `<环境Python>` 在 Windows 为 `.export-venv/Scripts/python.exe`，在 macOS / Linux 为 `.export-venv/bin/python`。用同一个解释器安装和执行：

```text
<环境Python> -m pip install -r scripts/export-requirements.txt
<环境Python> scripts/export_reviews_portable.py <安卓采集目录> <输出.xlsx>
<环境Python> scripts/export_reviews_portable.py <CDP采集目录> <输出.xlsx> --config <本次adapter.json>
```

独立验收仅需 Python 标准库：

```text
python scripts/export_reviews_portable.py <采集目录> <输出.xlsx> --verify-only
```

CDP 数据的验收同样需要加 `--config <本次adapter.json>`。它会检查全部原文字段、数量、每条 G 列内嵌图、图片关系、冻结位置和 XLSX 完整性。更多命令及长评论处理见 [统一 Excel 交付](android-app-review-collector/references/excel-delivery.md)。

## 默认交付内容

每个商品交付一份 `.xlsx`，列为：序号、买家（匿名）、发表日期原文、购买规格原文、评论正文原文、星级原文、评论截图预览、证据文件、平台评价ID。多屏评论预览首尾截图，证据列列出全部截图；原始截图另行归档。

CSV / JSON 作为备份。缺图、导出失败或校验未通过时必须明确报告，不能只交 CSV 并宣称带图 Excel 已完成。没有原始截图时需在指定商品范围内补拍；缺失日期、年份、星级或评价 ID 不作推断。

## 使用范围与数据

只处理用户指定且正常可见的商品评论。遇到登录、验证码、限流、商品不一致或无新增时保存断点并停止；无新增不等于“已采完”。需要登录和 USB 授权时由操作者完成。页面截图可能包含买家显示名或头像，采集结果应按自己的使用范围妥善保存。

公开仓库只包含工具、合成测试和适配说明，不包含实际评价、截图、账号、密钥、Cookie、手机序列号、内部目录或浏览器用户数据。商品 ID、分享口令和本次会话细节已从公开材料移除；专用运行库和第三方二进制依赖不随仓库分发。

## 验证与版本

当前版本：`v1.2.0-beta.3`。保留 12 项本地 CDP 回归测试、安卓解析 / 导航测试及 7 项便携导出测试。带图 Excel 已用现有 50 条网页数据和 50 条真机数据，在 JS 与 Python 两种引擎中逐字段、列宽、行高和图片位置比较，并渲染检查；未在第二台物理电脑上实测。

当前公开版不附带真实测试材料；本地测试使用合成数据。问题反馈请说明平台、App / 浏览器版本、复现步骤和脱敏错误信息，提交前删去密钥、账号、商品私有信息及买家个人信息。
