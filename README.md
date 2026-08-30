# 授权书籍下载与模糊建库工具

Windows 桌面工具：按书名或 ISBN 检索、下载到指定目录、记录 SQLite 历史，并按主题、格式、匹配阈值和目标磁盘容量自动建库。

界面采用蓝白科技主题，并配有项目内置的芙宁娜主题透明装饰立绘。

## 功能

- 书名 / ISBN 检索，展示作者、出版社、年份、语言、格式和文件大小。
- 单本下载到指定目录；自动生成安全文件名。
- SQLite 下载历史、失败原因、重复下载检测、文件/目录快捷打开。
- 模糊建库：主题、附加匹配词、0–100 匹配阈值、PDF/EPUB/任意格式、最大检索页数、目标容量。
- 批量任务暂停、继续和停止；当前文件完成后再暂停/停止。
- 独立普通 Chrome 配置目录，正常执行站点 JavaScript 校验，不读取个人 Chrome 配置。
- 默认串行下载并限制请求间隔，磁盘保留 512 MB 安全余量。

## 直接运行

```powershell
.\.venv\Scripts\python.exe main.py
```

## 构建 EXE

程序使用 `assets/app_icon.ico` 作为 Windows EXE 图标（Hydro 水滴 + 开放书本的蓝白科技风图标），页眉中的芙宁娜视觉元素保持不变。

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

构建脚本会先运行测试，再生成并冒烟验证：

```text
dist\BookLibraryBuilder.exe
```

目标电脑需要安装 Google Chrome。EXE 内含构建时匹配的 ChromeDriver；Chrome 大版本变化后，Selenium Manager 会尝试获取匹配版本。

## 50 GB 人工智能本科书籍示例

在“模糊建库”页设置：

1. 主题：`人工智能`
2. 附加匹配词：`教材, 导论, 基础, undergraduate, textbook`
3. 匹配阈值：建议先用 `55`
4. 目标格式：`PDF`
5. 建库容量：`50`
6. 最多检索页：可先设 `100`，结果不足时再增加
7. 选择目录后点击“开始建库”

目标容量是上限；程序会为站点显示大小的四舍五入保留至少 1 MB / 2% 的单文件误差余量。最终容量取决于检索结果数量、格式、站点限额和实际可用内容。

## 数据位置

```text
%LOCALAPPDATA%\AuthorizedBookBuilder\settings.json
%LOCALAPPDATA%\AuthorizedBookBuilder\history.sqlite3
%LOCALAPPDATA%\AuthorizedBookBuilder\chrome-profile\
```

工具只应用于已获授权、开放许可或公版内容。首次下载或建库前，界面会要求确认使用范围。
