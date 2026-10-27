# /opt/Bible_talking 部署到 the-inner-office.me/Bible_talking/

本流程采用 Python + FastAPI + systemd，Nginx 复用现有域名和 HTTPS 证书。网站无需登录，所有访客共享语料。后端使用 `127.0.0.1:18080`，数据存放在 `/var/lib/bible-talking`，不运行 Docker。

本地已独立完成 npm 构建，通过 `local-preview/` 启动预览，并使用本地代理模拟 Nginx 剥离前缀：无斜杠地址跳转、JS/CSS 加载、健康接口和真实模型检索（50 条结果）均正常。目标服务器上的 Nginx 和 systemd 尚未执行，需按下文验收。

## 1. 更新子路径适配文件

旧发布包的 `/assets` 和 `/api` 是域名根路径，不能直接用于这个地址。请先将最新发布包上传服务器并覆盖到 `/opt/Bible_talking`。新包不包含 `.env`、运行数据或虚拟环境，因此不会覆盖这些文件。

如果只同步少量文件，需要更新整个 `frontend/dist/`，并上传 `deploy/nginx-inner-office.conf.example`、`deploy/inner-office.env.example`、`deploy/bible-talking-inner-office.service`。后端和启动器采用上一版已有文件。

新版的 `frontend/dist/index.html` 使用 `./assets/...`，API 使用当前页面所在目录的 `api/...`。Nginx 将无末尾斜杠的地址重定向到 `/Bible_talking/`，然后剥离 `/Bible_talking/` 前缀转发。大小写必须保持一致。

## 2. 准备 Python 环境

以下安装系统依赖的命令适用于 Ubuntu/Debian 的 apt 系统。使用 Python 3.12 或 3.13；锁定依赖中的 NumPy 要求至少 Python 3.12，本项目已实际验证的 Python 为 3.13。

```bash
cd /opt/Bible_talking
python3 --version
sudo apt update
sudo apt install -y python3-venv python3-pip libstdc++6 libgomp1 ca-certificates
```

确认 `python3` 是 3.12 或 3.13 后执行：

```bash
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install -r requirements-lock.txt
```

如果系统默认是 3.10/3.11，需要先安装 3.12/3.13 和对应 venv 包，再用例如 `python3.13 -m venv .venv`。不要用低版本直接安装当前锁定依赖，也不要将 Windows 的 `.venv` 复制到 Linux。如果已有 Linux 虚拟环境，可以检查 `.venv/bin/python --version`，版本合适则直接安装依赖。

前端已构建，服务器不需要 npm。首次安装及模型下载需要服务器能访问依赖源和模型下载源。

## 3. 设置运行参数

先检查端口是否空闲：

```bash
sudo ss -ltnp 'sport = :18080'
```

如果有进程占用，选择其他空闲端口，并同步修改 `.env` 和 Nginx 中的端口。

首次部署或替换旧配置时，先备份已有 `.env`：

```bash
cd /opt/Bible_talking
if [ -f .env ]; then sudo cp -a .env ".env.backup.$(date +%Y%m%d-%H%M%S)"; fi
sudo install -m 600 deploy/inner-office.env.example .env
```

配置内容：

```dotenv
DEPLOYMENT_MODE=server
PUBLIC_ORIGIN=https://the-inner-office.me
BIND_HOST=127.0.0.1
PORT=18080
PRELOAD_BIBLE=1
QDRANT_URL=
```

`PUBLIC_ORIGIN` **不能带 `/Bible_talking`**；浏览器的 Origin 只有协议、主机和端口。`QDRANT_URL` 留空使用本地持久化向量存储；本流程不要求额外启动 Qdrant 服务，也不增加 Uvicorn workers。

## 4. 安装 systemd 服务

```bash
id bible-talking >/dev/null 2>&1 || sudo useradd --system --user-group \
  --home-dir /var/lib/bible-talking --shell /usr/sbin/nologin bible-talking

sudo install -m 644 deploy/bible-talking-inner-office.service \
  /etc/systemd/system/bible-talking.service

sudo systemctl daemon-reload
sudo systemctl enable bible-talking
sudo systemctl restart bible-talking
sudo journalctl -u bible-talking -f
```

模板已经使用精确路径 `/opt/Bible_talking`。systemd 自动创建 `/var/lib/bible-talking` 并赋予服务账号写权限，原文、数据库、模型及向量索引都保存在这里。程序目录应允许 `bible-talking` 账号读取和遍历；如果以前配置了仅 root 可访问的目录权限，需针对项目目录调整读取权限。

首次启动先下载和预热模型，完成后才监听端口。按 Ctrl+C 只退出日志查看。出现 Uvicorn 启动信息后检查：

```bash
curl -f http://127.0.0.1:18080/api/health
```

应包含 `"status":"ok"` 和 `"deployment":"server"`。内置圣经索引在后台生成，网页“共享语料库”显示进度。此流程使用独立的新服务器数据目录，不自动迁移 `/opt/Bible_talking/data` 中可能存在的数据。

## 5. 接入当前 Nginx 的 HTTPS 站点

用以下命令定位当前生效的域名配置，输出只需在服务器本地查看：

```bash
sudo nginx -T 2>&1 | grep -n -E 'configuration file|server_name.*the-inner-office\.me'
```

备份对应配置文件，然后在 **已有 `server_name the-inner-office.me` 且监听 HTTPS 443 的 `server { ... }` 内**加入以下两个 `location`。保留主站的 `location /`、证书路径和其他路由。如果已有同名 `/Bible_talking` location，应修改它而不是重复添加。

```nginx
location = /Bible_talking {
    return 308 /Bible_talking/$is_args$args;
}

location ^~ /Bible_talking/ {
    proxy_pass http://127.0.0.1:18080/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_read_timeout 120s;
    client_max_body_size 12m;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy same-origin always;
}
```

`proxy_pass` 末尾的 `/` 必须保留，它使 `/Bible_talking/api/health` 转发为后端的 `/api/health`。`^~` 防止主站已有的 JS/CSS 正则 location 截走本应用资源。行为参照 [Nginx 官方文档](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass)。

如果主站在 `server` 层设置了 `auth_basic` 或访问限制，这些规则可能被子路径继承，需要结合原有配置明确允许该子路径公开访问；本应用本身没有登录。

检查配置，成功后重载：

```bash
sudo nginx -t && sudo nginx -s reload
```

域名已指向这台服务器且已有正常 HTTPS 时，无需改 DNS、另申请证书或开放 18080 公网端口。宝塔管理的 Nginx 应在该站点配置页面编辑这些 location，避免覆盖整个主站配置。

## 6. 验收

```bash
curl -I https://the-inner-office.me/Bible_talking
curl -f https://the-inner-office.me/Bible_talking/api/health
```

第一条应重定向到 `/Bible_talking/`，第二条返回健康状态。打开：

<https://the-inner-office.me/Bible_talking/>

输入“可以给我水喝吗？”进行检索，再打开“共享语料库”检查索引进度。

| 现象 | 检查 |
| --- | --- |
| 502 | `systemctl status bible-talking`、`journalctl -u bible-talking -n 100`；本机健康接口是否可访问 |
| JS/CSS 404、空白页面 | 是否更新了整个 `frontend/dist`；是否使用末尾斜杠；是否配置 `^~` |
| API 404 | `proxy_pass` 是否保留末尾 `/`；请求是否为 `/Bible_talking/api/...` |
| 来源不允许 | `PUBLIC_ORIGIN` 是否仅为 `https://the-inner-office.me`；修改后是否重启服务 |
| 服务启动失败 | Python 版本、依赖安装、模型下载网络、代码读取权限、18080 端口 |

## 更新和备份

以后更新代码和完整的 `frontend/dist/` 后，执行 `sudo systemctl restart bible-talking`。依赖变更时，再使用项目虚拟环境安装 `requirements-lock.txt`。只修改应用代码不需要重载 Nginx。

备份时先停止服务，完整保存 `/var/lib/bible-talking/` 和 `/opt/Bible_talking/.env`，再启动服务；不要只备份程序目录。当前使用单进程和本地 Qdrant，完整预置语料会触发本地模式的大数据量提示，但不影响初次部署；后续可以独立评估迁移 Qdrant 服务，迁移时需重建索引。

## 低资源更新

更新 `backend/` 后重启即可启用：每批 8 条、单线程、关闭 ONNX CPU 内存池、闲置 60 秒卸载模型、每批索引暂停 0.1 秒。模型闲置后的首次搜索需要重新加载；现有语料和索引直接沿用。

已有服务安装下面的 drop-in，可保留实际的 `venv` 路径、启动参数和数据目录，同时降低运行优先级，将整个应用限制到半个 CPU 核心。先用 `systemctl cat bible-talking` 确认这是当前应用服务，再在更新后的代码目录执行：

```bash
cd /opt/Bible_talking
sudo install -d /etc/systemd/system/bible-talking.service.d
sudo install -m 644 deploy/low-resource.conf /etc/systemd/system/bible-talking.service.d/low-resource.conf
sudo systemctl daemon-reload
sudo systemctl restart bible-talking
curl -f http://127.0.0.1:18080/api/health
```

这里的 `CPUQuota=50%` 表示半个核心的总算力；`Nice=10`、`CPUWeight=10` 和 `IOWeight=10` 让繁忙时其他服务获得更高调度权重。数学库和分词器也使用节制并行的环境配置。要进一步减小推理峰值，可在现有 `.env` 中设置 `EMBEDDING_BATCH_SIZE=1`，然后重启。

观察索引完成、搜索之后和闲置约 65 秒时的内存：

```bash
systemctl show bible-talking -p MainPID -p MemoryCurrent -p CPUQuotaPerSecUSec
ps -p "$(systemctl show bible-talking -p MainPID --value)" -o pid,%cpu,%mem,rss,vsz,etime,args
curl -s http://127.0.0.1:18080/api/corpora
```

`rss` 单位为 KiB；`pending_jobs` 为零表示当前索引队列处理完毕。本地 Qdrant 的向量和元数据仍在内存中，闲置卸载针对模型及推理缓冲。Linux/glibc 环境在卸载后还会尝试归还空闲堆内存。CPU 限额会降低搜索和索引速度。

## 服务器无法下载模型时：使用离线模型包

日志出现 `Could not download model from HuggingFace: [Errno 101] Network is unreachable`，说明启动器已执行到模型准备阶段，但下载连接失败。无需重建 Python 环境，可以上传开发机已经缓存的模型。这个日志本身不能区分具体是路由、出口限制还是其他网络配置问题。

在开发机运行 `.venv\Scripts\python.exe scripts\package_model.py` 会生成独立模型 ZIP 和 SHA-256 文件。该包只含模型缓存、许可和校验清单，不包含用户语料；缓存元数据的 Windows 路径分隔符已转换为 Linux 可用的形式。2026-10-22 生成的 `Bible_talking-Model-46fbe35fd437.zip` 大小约 52.8 MiB，已解压校验所有文件并在禁用 socket 连接的条件下成功运行 512 维模型推理。

将模型 ZIP 上传到服务器 `/opt/Bible_talking/`，在服务器执行：

```bash
sudo systemctl stop bible-talking
sudo install -d -o bible-talking -g bible-talking /var/lib/bible-talking/models
sudo unzip -o /opt/Bible_talking/Bible_talking-Model-46fbe35fd437.zip -d /var/lib/bible-talking
sudo chown -R bible-talking:bible-talking /var/lib/bible-talking/models
```

编辑 `/opt/Bible_talking/.env`，加入或更新下面两项，避免保留重复键：

```dotenv
MODEL_CACHE_DIR=/var/lib/bible-talking/models
HF_HUB_OFFLINE=1
```

用户若已将服务器虚拟环境改为 `venv`，使用以下命令验证；仍使用 `.venv` 时替换对应路径：

```bash
sudo -u bible-talking env HF_HUB_OFFLINE=1 \
  MODEL_CACHE_DIR=/var/lib/bible-talking/models \
  /opt/Bible_talking/venv/bin/python /opt/Bible_talking/scripts/warm_model.py
```

输出 `Embedding ready: 512 dimensions` 后执行：

```bash
sudo systemctl restart bible-talking
sudo journalctl -u bible-talking -f --since '2 minutes ago'
```

只修改 `.env` 不需要 `daemon-reload`。Nginx 配置无需变更。模型加载完成后用 `curl -f http://127.0.0.1:18080/api/health` 验证服务，内置语料索引仍会在后台建立。
