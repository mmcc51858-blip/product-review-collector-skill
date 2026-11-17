# v1.1 界面导航测试

状态：v1.1.0-beta.2 已完成一次双口令真机测试，各 50 条评价。稳定基线保留 v1.0.0-review-collector，尚未验证通用无人值守批量采集。实测范围和限制见 [真机验收记录](batch-ui-validation.md)。

本方法在用户已经打开的商城内，通过剪贴板识别商品口令，再依据当前控件与截图进入详情和评价。底层继续使用 ADB 传输输入和截图。`phone_ui.py` 不包含启动应用、启动链接 Intent、修改系统设置或读取剪贴板的能力。

## 两商品验证

1. 用户提供两条商品链接或商城口令，明确每商品数量。本轮为每商品 50 条、综合排序、全部款式。
2. 用户打开商城。观察实际前台包名，不能因为装有多个抖音版本就猜目标应用。
3. 商城口令优先走剪贴板识别，不直接当搜索关键词。`phone_clipboard.py` 使用 scrcpy 5.0.1 的 SET_CLIPBOARD 控制消息，只写用户提供的完整分享文案，关闭剪贴板自动同步，不读取已有剪贴板。先核对官方服务端文件的 SHA256，下载依赖不进入版本包。
4. 已验证流程：`resume_shop.py ... background` 切到最近任务，写入完整分享文案，再 `resume_shop.py ... resume` 返回已存在的商城任务。观察实际商品弹窗并点击“查看详情”。必须先完成最近任务 XML 捕获，按“抖音商城”的准确卡片定位，不能按动画帧坐标点击。
5. 每一步都刷新截图，核对商品标题/ID和规格。不能只凭两个口令的同名标题认定同一商品。
6. 依据实际评价入口进入列表，再调用采集器并显式指定 `--limit 50`。
7. 每商品使用独立任务目录，保存导航截图、商品身份、评论和图片。若两条口令指向同一商品，报告重复目标，不能把同一批评论伪称为两个不同商品的数据。
8. 第二商品导航与采集成功后，输出测试报告：入口路径、唯一评论数、图片证据、是否人工接手、失败原因及稳定版差异。

达到目标条数后检查最后一条的图片是否跨屏。本次第 50 条的图片在停止页仅露出顶部，追加一次正常滚动并补拍后，只将新证据关联已有评论，不把新出现的第 51 条计入结果。

控件不唯一、页面变动、输入未聚焦时重新观察。工具策略拒绝某动作时停止该动作，不通过别的命令或工具绕过。只有页面正常加载且身份已核验才继续。

本轮发现：中文输入法可能把 ASCII 口令改成中文或全角符号；输入后必须逐字核对，未核对禁止提交。口令搜索可能显示“无匹配结果”并混入同名推荐商品，这些推荐不能当作目标链接验证成功。手机锁屏时由用户解锁，脚本不解锁或修改锁屏设置。

scrcpy 来源与协议：https://github.com/Genymobile/scrcpy/releases/tag/v5.0.1 ，https://github.com/Genymobile/scrcpy/blob/v5.0.1/app/src/control_msg.c 。剪贴板收到 ACK 只证明写入完成，必须再观察商城弹窗验证商品解析。

## 复用条件与依赖

用户先连接、授权并解锁安卓手机，在前台打开已登录的抖音商城。执行期间保持解锁，避免用户同时触屏。手机端无需运行 Codex。电脑需要 Python、官方 Android Platform Tools 和 scrcpy 5.0.1 服务端；导表默认使用统一格式；没有专用运行库时使用包内 Python 便携导出器，见 [Excel 交付](excel-delivery.md)。

- Platform Tools：https://developer.android.com/tools/releases/platform-tools
- scrcpy 服务端：https://github.com/Genymobile/scrcpy/releases/download/v5.0.1/scrcpy-server-v5.0.1
- 服务端 SHA256：`764eb6f79811d5211fe9df341120882ba9994c7a61b897d7bf3fb662e53bc536`

只下载此服务端，不要求安装完整 scrcpy 桌面程序。服务端通过临时 ADB 控制连接写入分享文本，完成后关闭连接和对应转发。用户原有剪贴板会被本次分享文本覆盖，不声称已恢复。

此流程由电脑端 Codex 逐屏判断并调用辅助脚本，不是脱离代理的一键批处理器。商品弹窗在本次设备上没有可用 XML 控件，须先查看新截图，再按实际“查看详情”按钮位置点击；不能复用上一商品的坐标，也不能点顶部“打开抖音”的跨应用提示。普通详情/评价入口优先按已观察控件定位。没有弹窗时重观或重新走背景写入流程，不能改点首页推荐。

本次抖音商城适配：实际包名 `com.ss.android.ugc.livelite`，评价列表 `com.ss.android.ugc.livelite:id/c7g`，正文左边界 44，规格左边界 177。均为现场观察值，复用到其他设备或版本须重新核验。配置 `sku_left` 排除“全部 / 图/视频”等页面筛选文本。

示例参数：
```text
python scripts/phone_ui.py --adb <路径> --serial <设备> --package <实际前台包名> --out <导航证据目录> snapshot
python scripts/phone_ui.py --adb <路径> --serial <设备> --package <实际前台包名> --out <导航证据目录> tap --node <索引>
python scripts/resume_shop.py --adb <路径> --serial <设备> --package <实际前台包名> --title 抖音商城 --out <导航证据目录> background
python scripts/phone_clipboard.py --adb <路径> --serial <设备> --server <scrcpy服务端路径> --text-file <UTF8分享文案文件> --out <该商品任务目录>
python scripts/resume_shop.py --adb <路径> --serial <设备> --package <实际前台包名> --title 抖音商城 --out <导航证据目录> resume
```
