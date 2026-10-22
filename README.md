# Bible_talking

**输入日常表达，查找可以直接引用的原文与出处。**

Bible_talking 是一个以本地语义检索为核心的语料工具，预置简体《和合本》圣经，也支持导入自己的文本。它从已有语料中返回原文片段，方便查看出处、阅读上下文和复制引用；目前不生成或改写经文。

支持开放网页版、浏览器本地运行、Windows 便携版和 Android 离线版。网页版模型在服务器执行，离线版在本机执行，无需配置云端模型 API Key。

## 主要功能

- **语义检索**：使用中文 BGE-small-zh-v1.5 模型理解查询，默认返回最多 50 个不同原文片段，可切换为 20 或 100 条。
- **原文与出处**：显示原文、出处和译本，支持复制“原文＋出处”或“仅原文”，并展开前后文；节内摘录标注为“节选”。
- **内置圣经**：预置简体《和合本》66 卷、31,100 节，保留本数据源的实际措辞、书名及章节，不补写缺失经节。
- **自定义语料**：支持 UTF-8 编码的 TXT、Markdown、JSON、JSONL，也可上传 ZIP 批量导入，提供切分预览、后台索引、进度和失败重试。
- **语料管理**：支持创建语料库、移除资源、删除与恢复语料库；新索引完整建立后才替换旧索引。
- **本地保存**：Windows 与浏览器后端使用 SQLite 和 Qdrant；Android 使用 IndexedDB 和本地向量检索。

检索结果按相关性排序，不显示相似度分数。当前未设置相似度阈值，因此返回结果不代表每条都适合直接引用，使用前请结合上下文判断。

## 选择使用方式

| 方式 | 运行要求 | 数据位置 |
| --- | --- | --- |
| 开放网页版 | Linux 服务器、现有 Nginx；Docker Compose 或 Python 服务 | 服务器持久化数据目录，所有访客共享 |
| Windows 便携版 | Windows 10/11 x64、Microsoft Edge WebView2 Runtime | 程序目录中的 `data/` |
| Android 离线版 | Android 8.0+、ARM64、系统 WebView 95+ | 应用内部存储 |
| 源码运行 | Python 3.12/3.13、Node.js 22；以下命令使用 Windows PowerShell | 默认项目目录中的 `data/` |

Windows 和 Android 离线包均包含模型、圣经正文与预置索引，不需要安装 Python、Node.js 或 Docker。手机与电脑的语料独立保存，目前没有自动同步。

### Windows 便携版

完整解压 `Bible_talking-Windows-x64-offline.zip` 到有写入权限的目录，双击 `Bible_talking.exe`。请保留包内的 `_internal/`、`models/`、`data/` 和 `portable.txt`，不要只复制 EXE。

更新前退出程序，保留现有 `data/`、`models/` 和 `portable.txt`，避免用新版初始数据覆盖自己的语料。程序尚未进行商业代码签名。更多说明见 [Windows 使用说明](desktop/使用说明.txt)。

### Android 离线版

安装离线 APK，建议至少预留 500 MB 存储空间。应用未申请联网权限，首次使用也无需下载模型或索引。

更新时覆盖安装使用同一签名的新 APK；卸载或清除应用数据会删除自定义语料。大量文本建索引时请保持应用在前台；被系统终止的任务会在下次启动时重新处理。

当前尚未完成 Android 真机或模拟器验收，桌面浏览器测试不能替代设备验证。详见 [Android 使用说明](android/使用说明.txt) 和 [Android 实现与验证](docs/android.md)。

安装包由下文的构建流程生成到 `release/`，不随源码提交；发布到 GitHub 时可作为 Release 附件上传。

## 从源码运行

以下命令均在项目根目录执行。已有开发记录使用 Python 3.13.5、Node.js 22.18.0。

### 1. 安装依赖

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
npm --prefix frontend ci
```

如果 `venv` 的 `ensurepip` 步骤失败，但虚拟环境解释器已经创建，可通过已有 pip 安装：

```powershell
python -m pip --python .venv\Scripts\python.exe install -r requirements-lock.txt
```

### 2. 下载并缓存模型

```powershell
.venv\Scripts\python.exe scripts\warm_model.py
```

首次执行需要联网下载模型，默认缓存在 `data/models/`。模型就绪后可离线运行。

### 3. 启动本地预览

```powershell
powershell -ExecutionPolicy Bypass -File local-preview\start.ps1 -Offline
```

打开 [本地页面](http://127.0.0.1:5173/)。脚本同时启动前端和后端，分别使用 `5173` 和 `8000` 端口。首次启动会导入内置正文并在后台建立索引，已完成的卷可以先检索，完整进度可在语料库页面查看。

停止预览：

```powershell
powershell -ExecutionPolicy Bypass -File local-preview\stop.ps1
```

运行数据、上传文件和默认模型缓存均位于 `data/`，已由 `.gitignore` 排除。备份时请保留该目录。

### 构建后运行

构建前端后，后端会直接托管 `frontend/dist/`，无需同时运行 Vite：

```powershell
npm --prefix frontend run build
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

请先停止占用同一数据目录或端口的旧进程，再打开 [构建后的页面](http://127.0.0.1:8000/)。也可由静态服务托管 `frontend/dist/`，并将 `/api` 代理到后端。

### 开放网页版（自有服务器 + Nginx）

网页版按公开共享模式运行，不需要登录，所有访客均可搜索、上传和管理同一套语料。前端构建后由后端直接托管，已有 Nginx 代理到本机后端端口即可。

已提供 `compose.server.yaml`、`Dockerfile`、Nginx 配置及可选 systemd 服务。完整步骤、数据备份和验证边界见 [服务器部署说明](docs/server-deployment.md)。可运行 `scripts/package_server.py` 将已构建网页与后端打包到 `release/`。

安装到 `/opt/Bible_talking`，通过 `https://the-inner-office.me/Bible_talking/` 访问时，请使用 [专用 Python + systemd 部署流程](docs/inner-office-deployment.md)。新版网页已支持子路径，配置保留现有主站路由。

内部所有者仍为 `1`；当前没有私人语料隔离或 Metalks 数据互通。

## 配置与存储

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `DATA_DIR` | 项目目录下的 `data/` | 源码后端的数据目录 |
| `MODEL_CACHE_DIR` | 数据目录下的 `models/` | 模型缓存目录 |
| `QDRANT_URL` | 空 | 留空使用持久化本地模式，设置后连接独立 Qdrant 服务 |
| `PRELOAD_BIBLE` | `1` | 设为 `0` 可禁用启动时自动导入内置圣经，适用于独立测试库 |
| `HF_HUB_OFFLINE` | 未设置 | 模型已缓存后设为 `1`，启用离线模式 |
| `DEPLOYMENT_MODE` | `local` | `server` 启用公开共享网页版与域名来源检查 |
| `PUBLIC_ORIGIN` | 空 | 服务器模式的完整网站来源，如 `https://bible.example.com` |
| `BIBLE_TALKING_DATA_DIR` | 由桌面启动器确定 | Windows 桌面版的数据目录覆盖项 |

### Qdrant 本地模式

默认将向量保存在 `data/qdrant/`，无需 Docker。同一数据目录只能由一个应用进程打开，请勿启动多个 Uvicorn workers。完整预置语料已超过本地模式建议迁移到服务端的 20,000 点规模，大规模使用需评估独立服务。

### 独立 Qdrant 服务

项目提供 [compose.yaml](compose.yaml)。切换存储前先停止后端，再在同一个 PowerShell 会话执行：

```powershell
docker compose up -d qdrant
$env:QDRANT_URL = 'http://127.0.0.1:6333'
.venv\Scripts\python.exe scripts\reindex_all.py
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

切换后需要重建向量索引，不会重新下载原文。Compose 仅将 Qdrant 端口绑定到本机，并使用持久化 named volume；服务不可用时应用不会自动退回本地存储。

已有验证覆盖 Qdrant 本地模式，独立服务的启动、并发与性能仍需在可用的 Docker 环境验收。

## 导入自定义语料

在页面中创建语料库，选择文件，检查切分预览后导入。文件需使用 UTF-8 编码。

- **TXT / Markdown**：按文本内容切分，记录标题路径、段落号及字符位置。
- **JSON**：使用对象数组。
- **JSONL**：每行一个对象。
- **ZIP**：在“选择文件或 ZIP”中直接上传压缩包，也可拖入上传区。支持上述四种格式和子目录；勾选文件、检查各文件的切分预览后，一次确认批量导入。说明文件（如 README、SOURCES）和 `metadata` 目录默认不选；隐藏文件和其他格式会忽略。单个文件失败不会撤销已成功的文件，可只重试未完成项。

ZIP 在设备本地解压，再按文件提交至现有导入接口；网页版和离线前端共用此流程。压缩包最大 50 MiB，解压总量最大 100 MiB，最多 200 个文件或目录，包内每个文件最大 10 MiB。不支持加密包、ZIP64 或嵌套 ZIP。同一语料库中的同名、同内容文件沿用去重逻辑；不同目录出现同名文件时，会将目录加入资源名以便区分。导入页面显示的“导入完成”表示文件已提交，向量索引进度仍在下方资源列表中查看。

JSON 示例：

```json
[
  {
    "text": "今天的风很轻，适合慢慢走回家。",
    "citation": {
      "scheme": "document",
      "label": "我的随笔 · 秋日"
    }
  }
]
```

对应的 JSONL 示例：

```jsonl
{"text":"今天的风很轻，适合慢慢走回家。","citation":{"scheme":"document","label":"我的随笔 · 秋日"}}
```

`text` 必填；`citation.label` 可省略，默认使用文件名与记录序号。上传内容作为文本显示，不执行其中的 HTML。可使用 [三行示例文本](examples/three-lines.txt) 体验导入。

## 开发与验证

前端修改后，先使用 `local-preview/` 启动预览验证，再在预览器之外单独构建，并保留 `frontend/dist/` 供部署使用。

```powershell
npm --prefix frontend run build
New-Item -ItemType Directory -Force data\test-runs | Out-Null
.venv\Scripts\python.exe -m pytest -q --basetemp=data\test-runs\manual
```

`--basetemp` 必须指向专用测试目录，pytest 会清理其中内容。后端测试使用独立临时数据库与确定性向量替身验证业务行为；真实模型检索质量需要另行验收。

ZIP 解压校验测试：在 `frontend/` 运行 `node --test zip.test.mjs`。浏览器回归测试 `node zip-ui.test.mjs` 需要先用独立 `DATA_DIR` 启动本地预览，并设置 `MODEL_CACHE_DIR` 指向已有模型缓存；它会创建并归档测试语料库，勿连接正式数据库。默认使用本机 Edge，可通过 `PLAYWRIGHT_CHANNEL` 调整；通过 `ZIP_TEST_URL` 可切换到构建产物的访问地址。

历史验证记录见 [第一阶段验收](docs/verification.md) 和 [Android 实现与验证](docs/android.md)。目前尚未完成独立标注集上的检索质量评测。

## 构建离线发布包

以下打包流程使用 Windows PowerShell。先完成源码运行准备，使用默认 `data/` 和本地 Qdrant 建立内置圣经库，模型缓存应位于 `data/models/`。

### Windows

```powershell
.venv\Scripts\python.exe -m pip install -r desktop\requirements-build.txt
powershell -ExecutionPolicy Bypass -File desktop\build.ps1
```

脚本构建前端、准备干净圣经索引、调用 PyInstaller，并组装 `release/Bible_talking/`。验证后将整个目录压缩为 `Bible_talking-Windows-x64-offline.zip`。

`desktop/prepare_seed.py` 生成 `build/bible-seed/`，仅复用与内置正文片段完整匹配的圣经向量；发布包不包含开发环境的自定义语料。重新生成种子库前需保留或重命名旧目录，重新打包前也需保留旧发布目录，避免覆盖用户数据。

`Bible_talking.exe --smoke-test` 是打包验证入口，会创建测试语料，必须配合指向专用测试目录的 `BIBLE_TALKING_DATA_DIR` 使用。普通使用直接双击 EXE。

### Android

如尚未执行 Windows 打包，先生成干净种子库；已有 `build/bible-seed/` 时不要重复执行此步骤：

```powershell
.venv\Scripts\python.exe desktop\prepare_seed.py
```

然后执行：

```powershell
.venv\Scripts\python.exe android\setup_tools.py
.venv\Scripts\python.exe android\export_assets.py
.venv\Scripts\python.exe android\check_embedding.py
node frontend\offline.test.mjs
npm --prefix frontend run build
.venv\Scripts\python.exe android\build.py
```

工具下载到 `build/android-tools/`，无需全局安装 JDK 或 Android SDK。导出步骤同时生成离线测试所需的数据和模型对照样例；构建脚本输出 `release/Bible_talking-Android-arm64-offline.apk`，包名为 `org.bibletalking.app`。

**请私下备份 `build/android-signing/` 中的签名密钥与口令，不要提交或公开。** 后续覆盖安装必须使用同一签名。

## 项目结构

```text
backend/        FastAPI 接口、语料解析、索引任务与 Qdrant 检索
frontend/       Vue 3 页面、Android 离线 Worker 与业务测试
desktop/        Windows 启动器、种子库准备与打包脚本
android/        Android 原生桥接、ONNX 编码器与构建脚本
resources/      内置语料及来源清单
examples/       导入样例与附加语料示例
scripts/        模型预热、索引重建与语料准备工具
tests/          后端业务测试
local-preview/  本地预览启动、停止与验收工具
docs/           架构设计与验证记录
```

Windows 和浏览器后端使用 FastAPI、SQLAlchemy / SQLite、FastEmbed / ONNX Runtime 和 Qdrant，模型输出为 512 维向量。Android 使用原生 ONNX Runtime 推理、Web Worker 精确余弦检索与 IndexedDB，不依赖 Qdrant 或远程后端。设计细节及 Metalks 对接边界见 [架构文档](docs/architecture.md)。

## 数据来源与许可

- **内置圣经**：来自 [seven1m/open-bibles](https://github.com/seven1m/open-bibles)。项目保存的来源清单记录其简体《和合本》条目标记为 Public Domain；具体来源、计数和 SHA-256 见 [resources/manifest.json](resources/manifest.json)。`scripts/prepare_bible.py` 可从上游 USFX 重建 JSONL。
- **向量模型**：[BAAI/bge-small-zh-v1.5](https://huggingface.co/BAAI/bge-small-zh-v1.5)，通过 FastEmbed 使用 ONNX 版本。随项目保留的模型许可见 [BGE-LICENSE.txt](desktop/licenses/BGE-LICENSE.txt)。
- **第三方组件**：相关许可证位于 [desktop/licenses/](desktop/licenses/)，打包脚本还会收集依赖许可证。第三方代码、模型及语料各自遵循其许可。

当前仓库尚未提供项目代码的 `LICENSE`；上述数据与第三方组件许可不代表项目代码的授权条款。
