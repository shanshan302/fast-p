# Fast-P

面向 Windows 的电子元器件比价截图桌面工具。用户选择 Excel、平台和输出目录后即可运行，不依赖 Agent 或 Skill 编排长任务。

详细需求、边界和 fast-cli 评估见 [docs/architecture.md](docs/architecture.md)。

## 当前能力

- 按用户选择的平台顺序串行采集；
- 从当前 fast-cli 动态读取启用平台，内置列表覆盖现有 12 个平台；
- 首个满足型号、厂牌、MOQ 和价格规则的平台命中后短路；
- 一个任务只启动一个持久 Node 采集 Worker；
- Worker 一次只处理一个平台，每次请求结束关闭页面；
- 采集、比价规则、截图、数据和任务编排分别位于独立模块；
- SQLite 逐项保存状态，中断后继续；
- 实时显示采集、截图和导出进度；
- 提供“只采集”“只截图”“采集并截图”三个独立入口；
- 日志自动轮转，并可一键导出脱敏诊断包；
- 导出结果 Excel、截图、运行报告和完整 ZIP。
- 从界面导入 fast-cli Windows 运行 ZIP，校验后原子切换并保留上一版本。
- 从界面打开全部平台登录页，登录状态与任务数据分开保存。

截图顶部由工具生成 URL 证据栏，页面主体来自真实商品页面。

## Mac 开发环境

本项目固定使用 Python 3.12 开发。Homebrew Python 需要单独安装 Tk：

```bash
brew install python@3.12 python-tk@3.12
cd /Users/wangchongshan/workplace/code/fast-p
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
python main.py
```

如果直接访问 PyPI 较慢，可以只在安装命令后临时增加可用的镜像参数；项目文件不绑定特定镜像。

## 源码运行要求

- Python 3.10+
- Node.js 20+
- `/Users/wangchongshan/workplace/code/fast-cli` 或兼容的 fast-cli Worker 目录
- Google Chrome
- 已登录目标平台的专用 Chrome Profile

安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

Windows 源码调试启动：

```powershell
python main.py
```

桌面安装版将在后续 Windows 构建步骤中内置 Python、Node、fast-cli、Chromium 和全部依赖，最终用户不需要执行上述命令。

## 三种任务模式

- `只采集`：读取原始比价 Excel，串行采集并输出含商品链接的比价结果，不启动截图引擎；
- `只截图`：读取任何包含“商品链接”列的 Excel，只需要 Chrome 和专用 Profile，不需要 Node、fast-cli 或平台选择；
- `采集并截图`：完成采集、短路比价、截图和导出全流程。

日志保存在 `~/.fast-p/logs/`。界面的“导出诊断包”只导出脱敏日志、运行环境版本、任务状态计数和最后事件，不包含 Cookie、密码或 Chrome Profile。

## 模块边界

```text
fast_p/collection.py  持久 fast-cli Worker 客户端
fast_p/rules.py       纯比价和匹配规则
fast_p/screenshot.py  独立 URL 截图能力
fast_p/data.py        Excel、SQLite、报告和 ZIP
fast_p/workflow.py    任务编排
fast_p/runtime_update.py  fast-cli ZIP 安全导入和版本切换
fast_p/app.py         Tkinter 界面
```

`fast_p/engine.py` 只保留旧调用的兼容导入，新代码不再把能力写回这个文件。

平台优先级继续保持原业务顺序：华秋、猎芯、硬之城、立创、华强、圣禾堂；fast-cli 提供的其他启用平台按其配置顺序追加。导入新版 fast-cli 后界面会重新读取平台清单。

## 输入列

程序识别以下列名及常见英文别名：

- 敦煌 SKU（可选）
- 型号
- 标准厂牌
- 供货价
- 最小起订量

## 任务状态和输出

每个任务目录包含 `job.sqlite3`。相同 Excel、相同平台和相同输出目录再次启动时，已完成结果跳过，采集异常项重试，已有截图跳过。

```text
<输出目录>/<表名>_结果/
├── job.sqlite3
├── <表名>_比价结果.xlsx
├── 运行报告.txt
├── screenshots/
└── <表名>_比价结果_完整材料.zip
```

## 验证

Fast-P：

```powershell
python -m unittest discover -s tests -v
```

测试包含 1000 条模拟长任务、每 50 条临时故障、取消/断点恢复、Worker 超时恢复、三种任务模式和诊断包脱敏。

fast-cli：

```powershell
npm test
node bin/fast-scrape-worker.js --help
```
