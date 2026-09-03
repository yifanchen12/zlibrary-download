# 安全声明 / Security Policy

## 支持范围

当前维护版本为 `1.3.0`。安全修复优先针对当前版本和 GitHub Release 中明确标注的版本。

## 漏洞报告

请不要在公开 Issue 中发布可复现的漏洞细节、Cookie、访问令牌、完整下载 URL 或包含个人路径的日志。

优先通过 GitHub 仓库的私密漏洞报告功能提交；若该功能不可用，请通过仓库所有者 `yifanchen12` 的 GitHub 账号私信联系，并提供：

- 受影响版本、操作系统和 Python/Chrome 版本；
- 最小复现步骤和预期/实际行为；
- 仅包含必要信息的日志或截图；
- 对影响范围、利用条件和建议修复方向的说明。

请在提交前删除密码、Token、Cookie、个人文件路径、书籍下载地址中的临时参数及其他敏感信息。报告内容会按最小知情原则处理。

## 运行安全要求

- 仅使用经过核验的 HTTPS 来源；手动修改来源地址后，先验证域名、证书和站点所有权。
- 自动入口检测只接受 HTTPS `z-library.*` 根地址，且不会覆盖用户配置的自定义来源。维护 `source_registry.json` 时必须独立核验新域名及证书，不得将未经核验的第三方地址写入清单。
- 将 `%LOCALAPPDATA%\AuthorizedBookBuilder\chrome-profile\` 视为敏感目录；其中可能存在用户主动登录产生的 Cookie 和站点存储。
- 不要把 `settings.json`、`history.sqlite3`、Chrome 配置目录、下载历史或构建产物中的个人路径提交到公共仓库。
- 将外部下载文件按不可信输入处理，打开前进行安全扫描，不执行书籍压缩包中的脚本、宏或二进制文件。
- 不要在 Issue、构建日志或 Release 说明中发布凭据、Cookie、Token 或带认证参数的 URL。

## 设计说明

应用没有内置遥测、广告 SDK 或远程统计服务；检索词、详情页请求和下载请求会发送至用户在设置中指定的来源。启用入口自动检测时，应用最多每 6 小时从本项目的 GitHub 原始内容域名读取一次公开入口清单，请求中不包含用户检索词、Cookie、历史记录、令牌或本地路径。应用使用原生无窗口 Chrome 模式和独立配置目录，不读取用户个人 Chrome 配置；正常下载流程不会覆盖或删除既有文件。

---

The current maintained version is `1.3.0`. Report security issues privately, do not disclose credentials or session data, and treat all files retrieved from external sources as untrusted input. The application has no built-in telemetry or analytics, retrieves only the public source registry when automatic discovery is enabled, and uses a dedicated headless Chrome profile.
