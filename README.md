# zlibrary-download

[简体中文](README.md) | [English](README.en.md)

Windows 桌面端的授权书籍检索、下载与模糊建库工具。项目使用 Selenium 驱动独立的 Chrome 配置目录访问用户指定的书籍来源，使用 BeautifulSoup 解析检索结果，使用 SQLite 持久化下载历史，并通过 Tkinter 提供图形界面。

> **项目边界**：本软件只处理用户有权访问、下载或再分发的内容。它不实现 DRM 破解、登录绕过、验证码绕过、访问控制绕过或任何形式的凭据收集。使用者须自行确认版权、再分发授权、站点条款及所在司法辖区的合规要求。

## 功能范围

- **元数据检索**：按书名或 ISBN 检索，展示标题、作者、出版社、年份、语言、格式和站点标注的文件大小。
- **单本下载**：从详情页选择可用格式，下载至用户指定目录；文件名经过 Windows 保留字符清理，并在同名时生成不覆盖既有文件的唯一名称。
- **历史审计**：SQLite 记录检索词、来源标识、详情页 URL、预期/实际字节数、开始/完成时间、状态和错误信息。
- **模糊建库**：根据主题、附加关键词和 0–100 匹配阈值筛选结果，可限制 PDF/EPUB 等格式、最大检索页数和目标容量。
- **任务控制**：批量任务支持暂停、继续和停止；停止/暂停在当前文件完成或当前安全检查点生效。
- **请求节制**：默认串行处理并使用 3 秒请求间隔；目标磁盘保留 512 MiB 安全余量；站点限额、超时和空间不足会写入历史记录。
- **隔离浏览器**：使用 `%LOCALAPPDATA%\AuthorizedBookBuilder\chrome-profile\`，不读取用户个人 Chrome 配置；可选显示浏览器窗口以便诊断站点提示。
- **本地化界面**：蓝白高科技主题，页眉包含芙宁娜主题装饰图；EXE 使用 `assets/app_icon.ico` 的水滴与开放书本图标。

## 算法与容量约束

模糊匹配由 `bookbuilder/utils.py` 实现：标题序列相似度、查询词命中率、标题/作者/出版社包含关系和附加关键词命中率共同计算 0–100 分。建库任务按页串行扫描，使用来源标注大小进行预筛选，并额外保留 `max(1 MiB, 2%)` 的单文件误差余量；实际容量仍以下载完成后的文件大小为准。

## 运行环境

- Windows 10/11 x64（已在 Windows 11 上验证）
- Google Chrome（当前稳定版）
- Python 3.14.7（本仓库的验证版本）
- 构建环境额外需要 PyInstaller 6.22.2

## 安装与运行

```powershell
git clone https://github.com/yifanchen12/zlibrary-download.git
Set-Location .\zlibrary-download

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

运行测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 构建 Windows EXE

构建脚本会安装构建依赖、运行测试、调用 PyInstaller，并启动 `--smoke-test` 完成无界面冒烟验证：

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

输出文件：

```text
dist\BookLibraryBuilder.exe
```

构建过程会将 `assets/` 和构建时发现的 ChromeDriver 打入单文件 EXE。目标机器仍需安装 Google Chrome；当 Chrome 大版本变化时，Selenium Manager 会尝试解析匹配的驱动版本。

## 使用流程

1. 在“设置与授权”页确认来源地址、下载目录和请求间隔，并勾选授权确认。
2. 在“检索下载”页输入书名或 ISBN，执行检索并选择目标条目。
3. 点击下载按钮；程序会检查磁盘余量、写入 `downloading` 历史记录，完成后更新为 `completed`，异常则写入 `failed`。
4. 如需批量建库，在“模糊建库”页设置主题、关键词、阈值、格式、页数和容量上限，再启动任务。

例如构建“人工智能”主题、约 50 GB 的 PDF 书目：主题填写 `人工智能`，附加词填写 `教材, 导论, 基础, undergraduate, textbook`，阈值可从 `55` 开始，格式选择 `PDF`，容量填写 `50`，先用较小页数观察结果，再逐步增加。

## 本地数据位置

```text
%LOCALAPPDATA%\AuthorizedBookBuilder\settings.json
%LOCALAPPDATA%\AuthorizedBookBuilder\history.sqlite3
%LOCALAPPDATA%\AuthorizedBookBuilder\chrome-profile\
```

设置文件包含来源地址、目录、超时和授权确认状态；历史数据库包含上述元数据和本地文件路径。程序不会内置遥测、广告 SDK 或远程统计服务。

## 安全与隐私声明

1. **数据流向**：检索词、详情页请求和下载请求会发送至设置页中的来源地址；除该来源和用户主动访问的站点外，程序不设计额外的数据上报通道。
2. **浏览器会话**：独立 Chrome 配置目录可能包含用户主动登录后产生的 Cookie、缓存或站点存储。请将该目录视为敏感数据，不要复制到公共仓库或共享压缩包。
3. **凭据保护**：程序不要求提交密码、API Token 或私钥；仓库、日志和问题报告中不得粘贴任何凭据、Cookie、完整 URL 中的令牌或个人路径。
4. **文件安全**：下载文件来自外部站点，应按不可信输入处理。打开前请使用本机安全软件扫描，不要执行电子书压缩包中的脚本、宏或可执行文件。
5. **传输安全**：默认来源为 HTTPS；若手动改为其他地址，应先验证域名、证书和站点所有权。应用不会替用户判断来源是否可信。
6. **文件系统**：程序只在用户选择的下载目录和上述应用数据目录中写入；同名文件采用新名称，正常流程不覆盖或删除既有文件。
7. **发布完整性**：从 GitHub Release 下载 EXE 后，建议使用 `Get-FileHash .\BookLibraryBuilder.exe -Algorithm SHA256` 校验发布说明中的摘要。

更完整的漏洞报告和运行安全要求见 [`SECURITY.md`](SECURITY.md)。

## 项目结构

```text
main.py                 CLI 入口、版本与冒烟测试
bookbuilder/browser.py  Chrome 生命周期、页面解析和下载等待
bookbuilder/services.py 下载服务与模糊建库调度器
bookbuilder/database.py SQLite 历史记录
bookbuilder/config.py   设置与本地数据目录
bookbuilder/gui.py      Tkinter 用户界面
bookbuilder/models.py   数据模型
bookbuilder/utils.py    文件名、大小和匹配工具
assets/                 EXE 图标与页眉装饰资源
tests/                  单元测试和 HTML fixture
```

## 版本与发布

- 当前版本：`1.1.1`
- Windows 发布包：[BookLibraryBuilder.exe v1.1.1](https://github.com/yifanchen12/zlibrary-download/releases/tag/v1.1.1)
- 仓库默认分支：`main`

仓库未附带统一的开源许可证文件；除另行书面授权外，源代码和资源的使用应遵循仓库所有者的授权范围，第三方书籍内容不属于本项目的许可范围。
