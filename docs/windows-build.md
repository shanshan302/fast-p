# Windows 安装包构建

## 构建结果

构建脚本生成一个面向 Windows x64 的安装程序：

```text
dist\installer\Fast-P-Setup-<版本>.exe
```

同时生成可通过界面“更新 fast-cli”导入的运行时包：

```text
dist\runtime\fast-cli-runtime-win-x64-<版本>.zip
```

目标电脑不需要安装 Python、Node、npm、fast-cli 或 Chrome。安装目录内置：

- PyInstaller Python/Tk 运行时；
- Node.js `node.exe`；
- fast-cli、平台配置、策略和生产依赖；
- Python Playwright 及与之匹配的 Chromium；
- Fast-P 桌面程序。

登录 Profile、设置、日志和任务输出位于用户目录，不写入安装目录。升级或卸载程序不会主动删除：

```text
%USERPROFILE%\.fast-p
%USERPROFILE%\.fast-scrape-cli
```

## 构建机准备

仅构建机需要：

- Windows 10/11 x64；
- Python 3.12 x64，并提供 `py.exe`；
- Node.js 20 或更高版本，并提供 `node.exe`、`npm.cmd`；
- Inno Setup 6；
- Fast-P 和 fast-cli 源码；
- 能访问 Python、npm 和 Playwright 下载源的网络。

先检查：

```powershell
py -3.12 --version
node --version
npm --version
Test-Path "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
```

Node 主版本必须不低于 20。

## 一键构建

fast-cli 与 Fast-P 同级时：

```text
C:\work\fast-p
C:\work\fast-cli
```

执行：

```powershell
cd C:\work\fast-p
.\scripts\build-windows.cmd
```

fast-cli 位于其他目录时：

```powershell
.\scripts\build-windows.cmd -FastCliRoot "D:\source\fast-cli"
```

Inno Setup 安装在非标准目录时：

```powershell
.\scripts\build-windows.cmd -FastCliRoot "D:\source\fast-cli" -InnoCompiler "D:\tools\Inno Setup 6\ISCC.exe"
```

脚本会删除并重建项目内的 `.build` 和 `dist`，不会修改 fast-cli 源码目录。

## 构建阶段

脚本顺序执行：

1. 在 `.build\venv` 创建隔离 Python 环境；
2. 安装 Fast-P、PyInstaller 和 Python 依赖；
3. 复制构建机的 `node.exe`；
4. 将 fast-cli 复制到临时目录并执行 `npm ci --omit=dev`；
5. 下载 Python Playwright 对应的 Chromium；
6. 运行 Fast-P 与 fast-cli 测试；
7. 使用 PyInstaller onedir 生成 `dist\Fast-P`；
8. 使用内置 Node 对 fast-cli 和 Worker 做冒烟检查；
9. 生成 fast-cli 独立更新 ZIP；
10. 使用 Inno Setup 生成最终安装程序。

PyInstaller 使用 onedir 是有意选择：Chromium、Node 和平台策略本身就是目录型运行时，onedir 启动更快，也避免单文件 EXE 每次启动都解压数百 MB。

## 安装验收

建议在一台未安装 Python 和 Node 的 Windows 电脑上验证：

1. 运行 `Fast-P-Setup-<版本>.exe`；
2. 从开始菜单启动 Fast-P；
3. 确认 Node、fast-cli、Chrome 字段已经自动指向安装目录；
4. 点击“登录平台”，完成至少一个目标平台登录，保持专用 Chromium 打开；
5. 使用 4 条数据执行“采集并截图”；
6. 确认结果 Excel、截图、运行报告和完整 ZIP 均生成；
7. 确认登录页不会被当成有效截图；
8. 再执行超过 100 条的任务，确认回收 CDP 后登录状态仍保留。

## 常见问题

### 找不到 py.exe

重新安装 Python x64，并启用 Python Launcher。构建脚本固定使用 `py -3.12`，不会使用 Microsoft Store 的不完整别名。

### 找不到 fast-cli

使用 `-FastCliRoot` 指定包含以下文件的目录：

```text
bin\fast-scrape-worker.js
package.json
package-lock.json
```

### 找不到 Inno Setup

使用 `-InnoCompiler` 指定 `ISCC.exe`。Inno Setup 只在构建机需要，目标电脑不需要。

### “表达式或语句中包含意外的标记”

先拉取最新代码，再使用单行 CMD 入口，不要复制带反引号的多行 PowerShell 命令：

```powershell
git pull
.\scripts\build-windows.cmd -FastCliRoot "D:\source\fast-cli"
```

构建脚本本身只使用 ASCII 文本并要求 Windows PowerShell 5.1，以避开旧版 PowerShell 的 UTF-8 脚本编码问题。

### Chromium 下载失败

检查构建机网络或代理后重新执行。`.build` 和 `dist` 是可删除的构建产物，脚本会从头重建。

### Windows 提示“未知发布者”

当前脚本生成未签名安装包，内部测试可以继续安装。正式外发时应购买代码签名证书，并在发布流程中对 `Fast-P.exe` 和安装程序签名；不要通过关闭系统安全功能来规避提示。
