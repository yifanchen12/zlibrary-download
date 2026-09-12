# 须弥首页视觉重做（用户已确认）

## 目标与范围

以用户提供的绿白金森林宫殿概念图为参考，重做 zlibrary-download 的 Tkinter 前端。保留已有未提交的主题修改与纳西妲资源，不改小说下载器或其他项目。收藏、内置阅读器与阅读进度尚不存在，本轮仅明确显示未支持状态，不扩建业务。

## 复用调查（已核实）

- `bookbuilder/gui.py`：Tkinter/ttk、SUMERU_THEME、消息队列、搜索/模糊建库/下载历史/设置页面。
- `Book`：标题、作者、格式、大小、详情及封面 URL；下载历史没有持久化封面字段。
- `HistoryDatabase.recent()`：真实下载记录；`single_progress` 和 `batch_event`：真实任务进度。批量暂停仅在现有安全检查点生效。
- `assets/nahida_header.png`：现有透明角色素材，可复用；缺少森林宫殿背景。
- Pillow 已安装，但尚未列入运行依赖；本轮使用其图片缩放能力时显式声明。

## 文件边界

- `bookbuilder/gui.py`：主题 tokens、侧栏、搜索页眉、首页横幅、分类与书卡、任务摘要，以及必要的 UI 事件投影；原操作入口与业务校验保留。
- `assets/sumeru_palace.png`：新生成的无文字森林宫殿背景；复用角色与图标，不把概念图直接贴成不可交互界面。
- `requirements.txt`：声明已使用的 Pillow 版本。
- `tests/test_ui_theme.py`：保留既有检查，增加主题素材和界面功能回归检查；测试使用临时数据库与合成书目，不访问真实站点或私人书库。
- `README.md`、`README.en.md`：准确说明新视觉、现有能力及空态。
- 不改：`browser.py`、`services.py`、`database.py`、`models.py`、`config.py`、`source_discovery.py` 的业务接口与数据结构。

## 接口与不变量

- 首页搜索将文本写入现有 `search_query`，调用 `_start_search()`；空词仍走现有提示，失败仍经消息队列展示。
- 分类卡片复用 `_prepare_topic(query, extras)`；已有导航继续由 `_show_page(index)` 驱动。
- 书卡输入只来自真实 `Book` 或下载历史；无可用封面时生成文字书封，不编造书目、评分或推荐排序。
- 下载任务消费现有 `single_progress(current,total,title)` 与批量事件。未知总量不生成虚假百分比；暂停/继续/停止复用原批量控制。
- 收藏与阅读不模拟持久化；明确空态，不显示虚假页数或百分比。
- UI 回归测试隔离 Settings、数据库、浏览器/发现入口；不读取用户个人配置、下载或发送网络请求。

## 实施顺序与验收

1. 生成背景、验证复用素材和独立主题组件。
2. 组合侧栏/页眉/首页模块，以合成数据验证空态、书卡及缩放。
3. 接入现有操作和任务事件，验证搜索、分类、历史导航、进度及错误状态。
4. 运行 `python -m unittest discover -s tests -v`；对常用与最小窗口做截图检查；沿用现有 PyInstaller 入口验证 EXE。

## 已决定 / 待观察

- 已决定：沿用 Tkinter，不迁移 Web/Electron；本轮不扩建收藏或阅读后端。
- 首版书卡使用文字封面，不新增远程封面抓取协议。未来若已有可靠封面缓存再接入。
- 窗口宽度不足时首页滚动/重排，不隐藏重要操作。具体断点由运行截图验证。

## 实施中修订：本地运行库

已实测此机器的 Python 3.14.7 找不到标准目录下的 Tcl/Tk，但安装自带 `tcl/libtcl*.zip` 与 `libtk*.zip`。在 `gui.py` 的 UI 入口增加本地库加载函数；正常 Python 和打包版继续使用自带标准运行库。测试/构建使用工作区缓存，正常运行使用应用 runtime 缓存，不下载运行时代码。其他边界不变。

构建验证同样需要本地 Tcl/Tk 路径，因此 `build.ps1` 复用该加载函数后调用原 PyInstaller 参数，并在依赖/测试失败时停止。打包冒烟验证改用 `build/smoke-profile` 合成配置，避免读取私人设置或历史；不修改主程序业务入口。

## 本轮验收结果（2026-09-12）

- `python -m unittest discover -s tests -v`：26 项通过；覆盖现有核心逻辑，以及隔离环境下的首页搜索、实际下载服务写入合成文件、书卡导航、打开最近文件、分类填入、暂停/继续/停止、失败与未知总量状态。
- 1600 × 940 / 1100 × 760 截图已检查；窄窗口可滚动到底部操作，其他页面可横向滚动；修复了重排后滚动范围更新和卡片文字裁切。
- `build.ps1` 构建与隔离 `--smoke-test` 通过；最新 EXE 另行验证真实 GUI 启动、窗口截图与正常关闭。
- 原 UI 下载回调曾在工作线程读取 Tk 变量；现在启动线程前读取查询字符串，避免非主线程 Tcl 调用。下载服务、数据库、浏览器与入口发现模块保持不变。
- 生成资源：`assets/sumeru_palace.png`；模式与最终提示词见 `assets/README.md`。文档截图 `docs/sumeru-home.png` 仅含合成书目与进度。
- 启动：项目目录下执行 `.\.venv\Scripts\python.exe main.py`，或打开 `dist/BookLibraryBuilder.exe`。构建仍使用 `powershell -ExecutionPolicy Bypass -File .\build.ps1`。
- 未验证真实外网站点可达性或真实书籍下载；收藏、内置阅读器及阅读进度不在本轮实现范围。既有角色贴图的来源与再分发许可未独立核实。
- 未提交或推送 GitHub；保留开始时已有的图标、角色资源与文档修改，不更改其他项目。

## 第二阶段：收藏、阅读与进度（用户已确认）

### 需求解释

补齐当前界面明确标记为未支持的收藏、阅读记录与轻量内置阅读能力。EPUB、TXT、Markdown、HTML 在应用内阅读；PDF 及其他格式继续调用系统关联程序。应用内阅读自动保存滚动进度，外部阅读只记录打开行为，不推测页码。

### 复用调查

- 复用 `HistoryDatabase` 的 SQLite 连接、事务和本地下载记录，不引入新数据库层。
- 复用 `Book`、`DownloadService.download()`、现有搜索结果与历史选中逻辑。
- 复用 Tkinter `Toplevel`/`Text`，以及标准库 `zipfile`、`html.parser`、`xml.etree.ElementTree` 解析本地文本和 EPUB；不增加阅读依赖。
- 复用现有 `ScrollPage`、主题样式与 `_show_page()` 页面路由。

### 文件与接口边界

- `bookbuilder/database.py`：新增 `favorites`、`reading_states` 表及收藏切换、收藏列表、阅读状态保存/查询接口；已有下载表与方法不变。
- `bookbuilder/reader.py`：安全读取 UTF-8/常见中文编码文本、HTML/Markdown 与 EPUB 章节，返回纯文本；拒绝目录穿越、缺失书脊和超限内容。
- `bookbuilder/gui.py`：新增收藏页、阅读记录页、轻量阅读窗口；搜索、历史、首页入口接入收藏与继续阅读；PDF/未知格式仍走系统关联程序。
- `tests/test_core.py`：数据库生命周期和本地阅读解析检查。
- `tests/test_ui_theme.py`：七页导航、收藏、阅读记录与进度恢复的隔离交互检查。
- `README.md`、`README.en.md`：准确说明支持格式、进度语义与限制。
- 保持不变：`browser.py`、`services.py`、`models.py`、`config.py`、`source_discovery.py` 的下载、检索和设置协议。

### 轻量接口契约

- `toggle_favorite(book) -> bool`：按 `source_id` 切换并返回新收藏状态；不保存 Cookie 或正文。
- `favorites() -> list[sqlite3.Row]`：按最近收藏排序。
- `record_reading(download_id, progress=None) -> None`：更新打开次数和时间；仅在提供真实内置阅读位置时更新 0–1 进度。
- `reading_history() -> list[sqlite3.Row]`：仅返回仍关联下载记录的阅读状态。
- `read_document(path) -> str`：只读取本地受支持文件；输出纯文本，错误以简短可显示异常返回。
- 内置阅读器关闭时保存当前垂直位置；外部阅读器不生成虚假百分比。

### 实施与验收顺序

1. 独立实现数据库与阅读解析，并用临时 SQLite/合成文档验证。
2. 组合收藏、阅读状态与七页 UI，验证收藏切换、下载/打开入口、进度恢复和空态。
3. 接入首页、搜索与历史入口；运行完整测试、宽窄窗口截图、PyInstaller 构建与隔离 GUI 启动检查。
4. 检查差异与敏感信息后，提交全部本次须弥 UI 相关改动并推送 GitHub `main`。

### 已确认限制

- PDF 与未知格式由系统程序打开，应用只能记录打开时间和次数。
- EPUB 以书脊顺序提取纯文本，不执行脚本、不加载远程资源、不追求复杂 CSS 排版。
- 不增加云同步、批注、账户或推荐算法；这些不属于当前“剩余功能”。

### 第二阶段验收结果（2026-09-13）

- `python -m unittest discover -s tests -v`：29 项通过。新增覆盖收藏增删、收藏页打开已下载文件、阅读记录、真实滚动进度恢复、TXT/HTML/EPUB 解析、未知格式分流和危险 EPUB 路径拒绝。
- 七页导航、收藏页、阅读记录页及 1100 × 760 重排截图已检查；首页截图已更新为合成 PDF/TXT 记录，不包含私人书库。
- `build.ps1` 完成 1.4.0 单文件 EXE 构建和隔离冒烟测试；文件版本/产品版本均为 1.4.0。最终包另以隔离配置完成真实 GUI 启动、窗口截图及正常关闭。
- GitHub 目标已核实为公开仓库 `yifanchen12/zlibrary-download`，默认分支 `main`；提交与推送在完成差异审计后执行。
