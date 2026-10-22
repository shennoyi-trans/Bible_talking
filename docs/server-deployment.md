# 开放网页版与 Nginx 部署

网页版无需登录。所有访客共享同一套语料，均可检索、上传、创建、移除、删除和恢复语料库；上传的文字也对其他访客开放。没有账号、密码或会话 Cookie。

前端复用现有 Vue 界面，模型、SQLite 和向量检索在服务器执行。桌面版和 Android 仍保持原有本地行为。本文仅提供代码部署步骤，不会自动连接或修改你的服务器。

## 交付内容

- `frontend/dist/`：已经构建的网页，可直接交给后端托管。
- `compose.server.yaml`、`Dockerfile`：应用和独立 Qdrant 服务，使用持久化卷。
- `deploy/nginx.conf.example`：加入现有域名 HTTPS `server` 块的反向代理配置。
- `deploy/bible-talking.service`：不使用 Docker 时的 systemd 模板。
- `scripts/configure_server.py`：生成域名和端口配置，拒绝覆盖已有 `.env`。
- `scripts/package_server.py`：打包已构建网页、后端、配置、内置正文和说明；不包含本机私有语料、模型、密钥或开发环境。

在 Windows 开发机重新生成发布包：

```powershell
npm --prefix frontend run build
.venv\Scripts\python.exe scripts\package_server.py
```

生成的 ZIP 与 SHA-256 文件保存在 `release/`。服务器解压 ZIP 后不需要 Node.js。首次启动需要联网下载 Python 依赖、镜像和模型，模型下载后保存在数据卷中，后续重启复用。内置圣经正文已包含在包里，初次索引在后台进行，进度可在“共享语料库”查看。

## 方式一：Docker Compose + 现有 Nginx

适用于已安装 Docker Engine 和 Compose v2 的 Linux 服务器。将发布包解压到一个独立目录，例如 `/opt/bible-talking`，在该目录执行：

```bash
python3 scripts/configure_server.py --origin https://bible.example.com
docker compose -f compose.server.yaml up -d --build
docker compose -f compose.server.yaml logs -f app
```

把示例域名换成实际域名。没有 Python 时，也可复制 `deploy/server.env.example` 到 `.env` 并修改 `PUBLIC_ORIGIN`。端口 8000 已被占用时，生成配置可加 `--port 8100`，并同步修改 Nginx 的上游端口。应用容器内部始终使用 8000。

应用只发布 `127.0.0.1:8000`，Qdrant 不发布任何主机端口。域名和 TLS 继续由已有 Nginx 管理。此配置假定 Nginx 运行在同一台宿主机上；容器化 Nginx 应与应用加入同一网络，并使用 `app:8000` 作为上游。

### 接入现有域名

在对应域名的 HTTPS `server { ... }` 内合并 `deploy/nginx.conf.example` 内容，保留已有证书配置，替换原先的 `location /`，不要添加两个同名 `location /`。核心配置为：

```nginx
client_max_body_size 12m;
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_read_timeout 120s;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy same-origin always;
}
```

检查后重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
curl -f http://127.0.0.1:8000/api/health
curl -f https://bible.example.com/api/health
```

返回 `"status":"ok"` 和 `"deployment":"server"` 后，访问域名即可使用。健康检查表示 HTTP 服务已启动，不代表内置语料全部索引完成。首次模型下载完成前，后端尚未监听，Nginx 可能暂时返回 502；查看 `logs -f app` 确认进度。

新版前端使用相对资源与接口路径，支持域名根路径和子路径。子路径部署需要补齐末尾斜杠，并由 Nginx 去掉路径前缀再转发；参见 [the-inner-office.me 的部署流程](inner-office-deployment.md)。`PUBLIC_ORIGIN` 只填写浏览器实际使用的协议、域名和非默认端口，不带 `/Bible_talking` 等路径。建议使用 HTTPS，浏览器剪贴板功能需要安全上下文。

Nginx 的反向代理与超时配置参照 [Nginx 官方文档](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)。

### 更新与日志

保留 `.env` 和已有持久化卷，更新源代码及 `frontend/dist/` 后执行：

```bash
docker compose -f compose.server.yaml up -d --build
docker compose -f compose.server.yaml ps
docker compose -f compose.server.yaml logs --tail=100 app
```

启动器等待 Qdrant 就绪后预热模型，再启动一个 Uvicorn worker。应用进程和 Qdrant 异常退出后自动重启。HTTP 健康检查用于显示状态；Docker 不会仅因 `unhealthy` 自动重启容器。模型下载较慢时，可继续观察日志。不要增加 workers 或同时运行多个应用副本：索引工作队列目前采用单进程调度。

## 方式二：Python + systemd + 现有 Nginx

不使用 Docker 时，准备 Python 3.13 和 venv，以及 ONNX Runtime 所需的系统 C++ / OpenMP 运行库（Debian/Ubuntu 对应 `libstdc++6`、`libgomp1`），将文件放到 `/opt/bible-talking`：

```bash
cd /opt/bible-talking
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
python3 scripts/configure_server.py --origin https://bible.example.com
sudo useradd --system --home-dir /var/lib/bible-talking --shell /usr/sbin/nologin bible-talking
sudo cp deploy/bible-talking.service /etc/systemd/system/bible-talking.service
sudo systemctl daemon-reload
sudo systemctl enable --now bible-talking
sudo journalctl -u bible-talking -f
```

服务账号已存在时跳过 `useradd`。如果选择其他安装目录，需要修改 service 中的路径。服务默认监听 `127.0.0.1:8000`，Nginx 使用上一节的配置。systemd 为该账号创建可写的 `/var/lib/bible-talking`，存放 SQLite、上传正文、模型与向量索引；程序目录可保持只读。目录行为参照 [systemd 文档](https://www.freedesktop.org/software/systemd/man/258/systemd.exec.html)。

此方式默认使用 Qdrant 本地存储。要使用已有独立 Qdrant，可在 `.env` 加入 `QDRANT_URL=http://127.0.0.1:6333`；切换已有语料的存储方式必须重建索引。生产上可优先采用方式一的独立 Qdrant。

## 数据与备份

Docker 方式使用 `bible-talking_app_data`（SQLite、上传原文、模型）和 `bible-talking_vector_data`（Qdrant 索引）两个命名卷。更新镜像不会覆盖这些数据。不要使用 `docker compose down -v`，这会删除持久化卷。

Docker 冷备份示例（在项目目录执行，期间网站暂时不可用）：

```bash
mkdir -p backups
docker compose -f compose.server.yaml stop app qdrant
docker run --rm --user 0 --entrypoint tar \
  -v bible-talking_app_data:/snapshot/app:ro \
  -v bible-talking_vector_data:/snapshot/qdrant:ro \
  -v "$PWD/backups:/out" bible-talking:local \
  -czf /out/bible-data-$(date +%Y%m%d-%H%M%S).tar.gz -C /snapshot .
docker compose -f compose.server.yaml start qdrant app
```

同时保留 `.env` 和对应版本发布包。若修改 Compose 项目名称，卷名前缀也会变化，需要使用实际卷名。systemd 方式先停止服务，再完整备份 `/var/lib/bible-talking/`；若连接外部 Qdrant，还需单独备份它的存储。恢复时保持 SQLite 与向量索引来自同一份备份，并恢复数据目录所有权。

新部署默认从内置正文生成新库，不携带开发机自定义语料。若迁移已有本地数据到独立 Qdrant，先停止应用、迁移 SQLite 与原文，再设置正确的 Qdrant 地址执行 `scripts/reindex_all.py`；不能只复制 SQLite 后直接使用一个空向量库。

## API 与验证范围

公开 API 不需要登录或令牌。网页会在 POST/DELETE 等请求中附加公开的 `X-Bible-Request: 1` 标记；直接调用接口时也带上该标记。它仅避免其他网站通过普通表单误触发写入，不是权限验证。浏览器发送的 `Origin` 必须匹配 `PUBLIC_ORIGIN`；无 Origin 的脚本客户端可直接访问。

例：

```bash
curl https://bible.example.com/api/search \
  -H 'Content-Type: application/json' -H 'X-Bible-Request: 1' \
  -d '{"corpus_id":"corpus_cuv","query":"可以给我水喝吗？","top_k":20}'
```

本次本地验证通过 14 项后端测试，覆盖匿名共享语料、导入/检索/上下文/删除恢复、跨站来源校验、配置生成不覆盖已有文件，以及原有业务回归。已通过 `local-preview/` 以服务器模式检查界面，真实模型查询“可以给我水喝吗？”返回 50 条原文并可展开上下文，共享语料库页面正常显示；同时独立完成 npm 构建并检查后端托管的构建版页面。本机没有 Docker 和 Linux systemd，容器构建、Nginx TLS 接入及服务自启动尚需在目标服务器上验收。
