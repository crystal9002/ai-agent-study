# 部署文档

面向 Linux 服务器（裸机 / systemd + Nginx），把各教程的 Web 服务部署为常驻进程。

## 1. 服务概览

| 服务 | 目录 | 入口 | 默认端口 | 说明 |
|---|---|---|---|---|
| RAG 知识库 | `01-rag-knowledge-base-tutorial/` | `scripts/06_web.py` | 8000 | 检索问答，SSE 流式输出 |
| Task Agent | `02-agent-tutorial/` | `scripts/03_web.py` | 8001 | 规划型 Agent，SSE 进度推送 |
| 知识库 Agent | `03-knowledge-base-agent/` | `scripts/03_web.py` | 8002 | 检索+多步任务组合 |
| 评估观测仪表盘 | `04-llmops-eval/` | `scripts/05_web.py` | 8003 | 运行 trace / 评估历史 |
| Agent 安全审批台 | `05-agent-security/` | `scripts/03_web.py` | 8004 | SSE + 审批 + 审计日志 |
| MCP 多智能体 | `06-mcp-multi-agent/` | `scripts/04_web.py` | 8005 | supervisor/worker 泳道可视化 |

教程按序号学习，Web 服务可按需只部署其中几个（04/05 只依赖轻量包；01/03 需要本地 embedding 模型）。

各服务都是 FastAPI 单进程应用，静态页与 API 同端口，前端用**绝对路径**请求 `/api/*`，
因此**反向代理按端口（或独立域名）划分**，不要用子路径（如 `/rag/`）反代，否则前端 fetch 会 404。

## 2. 环境要求

- Linux x86_64，Python **3.10+**（推荐 3.12）
- 内存 ≥ 2GB（RAG 服务加载 embedding + rerank 两个本地模型，常驻约 1~1.5GB）
- 磁盘 ≥ 10GB（Python 依赖含 torch 约 2GB，HF 模型缓存约 1.6GB，向量索引很小）
- 纯 CPU 即可，不需要 GPU
- 一个 OpenAI 兼容的 LLM API Key（DeepSeek / OpenAI / 方舟等）
- 出网要求：能访问 LLM API；能访问 HuggingFace（不通则用镜像，见 §5）

## 3. 安装

```bash
git clone git@github.com:crystal9002/ai-agent-study.git
cd ai-agent-study

# ---- 每个教程各自建虚拟环境（按需取用，跑几个建几个）----
for d in 0*/; do
  python3 -m venv "$d/.venv"
  "$d/.venv/bin/pip" install -U pip
  "$d/.venv/bin/pip" install -r "$d/requirements.txt"
done
```

> 用 `uv` 可显著加速：`uv pip install -p <venv>/bin/python -r requirements.txt`。
> 框架对照脚本（`scripts/0*_lang*.py`、`04_framework.py` 等）需另装对应 `requirements-framework.txt`。

## 4. 配置 `.env`

每个目录各放一份（**已在 .gitignore，不要提交**）：

`01-rag-knowledge-base-tutorial/.env`：

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-xxxx
LLM_MODEL=deepseek-chat

# 本地模型（默认，无需额外 key）
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
RERANK_ENABLED=1
RERANK_MODEL=BAAI/bge-reranker-base

RETRIEVAL_MODE=hybrid
CHUNK_STRATEGY=recursive
VECTOR_STORE=faiss
INDEX_DIR=index

# 服务监听：裸跑默认 127.0.0.1，经 Nginx 代理保持默认即可；
# 如需直连暴露，改 HOST=0.0.0.0 并配合防火墙白名单
HOST=127.0.0.1
PORT=8000
```

`02-agent-tutorial/.env`：

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-xxxx
LLM_MODEL=deepseek-chat
HOST=127.0.0.1
PORT=8001
```

入口脚本启动时会自动 `load_dotenv()`（相对脚本定位，与工作目录无关）。

## 5. 构建知识库索引（仅 RAG）

把你的文档（`.md` / `.txt`）放进 `01-rag-knowledge-base-tutorial/data/`，然后：

```bash
cd 01-rag-knowledge-base-tutorial

# 国内服务器 HuggingFace 官方源不通时先设镜像
export HF_ENDPOINT=https://hf-mirror.com

.venv/bin/python scripts/01_build_index.py
```

- 首次运行会下载 embedding + rerank 模型到 `~/.cache/huggingface`（约 1.6GB），之后离线可用。
- 模型已缓存、服务器无法出海时，运行期加 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`，跳过每次启动的联网校验（systemd 模板里已带）。
- 增删改文档后**必须重建索引**再重启服务。

## 6. 手动验证（部署前必做）

```bash
# RAG
cd 01-rag-knowledge-base-tutorial
.venv/bin/python scripts/06_web.py &
curl -s http://127.0.0.1:8000/api/config
curl -sN -G http://127.0.0.1:8000/api/query --data-urlencode "q=团队版多少钱" | head -20

# Agent
cd ../02-agent-tutorial
.venv/bin/python scripts/03_web.py &
curl -sN -G http://127.0.0.1:8001/api/run --data-urlencode "goal=用calc算123*456" | head -20

# 知识库 Agent（先建库：scripts/01_build_kb.py）
cd ../03-knowledge-base-agent
.venv/bin/python scripts/03_web.py &
curl -sN -G http://127.0.0.1:8002/api/query --data-urlencode "q=团队版多少钱" | head -20

# 评估观测
cd ../04-llmops-eval
.venv/bin/python scripts/01_trace_demo.py && .venv/bin/python scripts/05_web.py &
curl -s http://127.0.0.1:8003/api/runs

# Agent 安全
cd ../05-agent-security
.venv/bin/python scripts/03_web.py &
curl -s http://127.0.0.1:8004/api/audit

# MCP 多智能体
cd ../06-mcp-multi-agent
.venv/bin/python scripts/04_web.py &
curl -sN -G http://127.0.0.1:8005/api/run --data-urlencode "goal=查团队版定价并算50人年费" | head -20
```

预期：`/api/config`、`/api/runs`、`/api/audit` 返回 JSON；query/run 返回 `event: ...` 开头的 SSE 流。
测完用 `kill %1 %2 ...` 或 `pkill -f scripts/0` 收掉后台进程。

## 7. systemd 常驻

`/etc/systemd/system/rag-web.service`：

```ini
[Unit]
Description=RAG Knowledge Base Web (port 8000)
After=network.target

[Service]
Type=simple
User=www
WorkingDirectory=/opt/ai-agent-study/01-rag-knowledge-base-tutorial
EnvironmentFile=/opt/ai-agent-study/01-rag-knowledge-base-tutorial/.env
Environment=HF_ENDPOINT=https://hf-mirror.com
Environment=HF_HUB_OFFLINE=1
Environment=TRANSFORMERS_OFFLINE=1
ExecStart=/opt/ai-agent-study/01-rag-knowledge-base-tutorial/.venv/bin/python scripts/06_web.py
Restart=on-failure
RestartSec=5
# 模型加载慢，给足启动超时
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/agent-web.service`：

```ini
[Unit]
Description=Task Agent Web (port 8001)
After=network.target

[Service]
Type=simple
User=www
WorkingDirectory=/opt/ai-agent-study/02-agent-tutorial
EnvironmentFile=/opt/ai-agent-study/02-agent-tutorial/.env
ExecStart=/opt/ai-agent-study/02-agent-tutorial/.venv/bin/python scripts/03_web.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rag-web agent-web
systemctl status rag-web agent-web
journalctl -u rag-web -f        # 看日志
```

> `EnvironmentFile` 会把 `.env` 注入进程环境；脚本内的 `load_dotenv()` 在变量已存在时不覆盖，两者不冲突。
> 注意 `.env` 若含 `export ` 前缀或纯注释行以外的特殊写法，systemd 解析会报错——保持 `KEY=VALUE` 即可。

> 03~06 的服务同方抓药：复制上面 unit，改 `WorkingDirectory` / `EnvironmentFile` / `ExecStart`
> （入口与端口见 §1 服务概览表），如 `03-kb-web`、`04-eval-web`、`05-sec-web`、`06-mcp-web`。

## 8. Nginx 反向代理（SSE 关键配置）

```nginx
server {
    listen 80;
    server_name rag.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # ---- SSE 必须项 ----
        proxy_buffering off;          # 否则事件被缓冲，前端收不到实时流
        proxy_cache off;
        proxy_read_timeout 300s;      # Agent 执行/长问答可能超过默认 60s
        proxy_send_timeout 300s;
    }
}

server {
    listen 80;
    server_name agent.example.com;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

生产建议加 HTTPS（certbot）与基础限流：

```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=5r/s;
# location /api/ { limit_req zone=api burst=10 nodelay; ... }
```

## 9. 安全清单

- [ ] `.env` 权限 `chmod 600`，不进 git、不进镜像层
- [ ] 服务只监听 `127.0.0.1`，公网仅经 Nginx 暴露
- [ ] 防火墙只开 80/443（`ufw allow 80,443 && ufw enable`）
- [ ] 所有 Web 均无鉴权——公网暴露时至少加 Nginx Basic Auth：
  ```nginx
  location / {
      auth_basic "restricted";
      auth_basic_user_file /etc/nginx/.htpasswd;
      ...
  }
  ```
- [ ] LLM Key 仅存于服务器 `.env`，泄露即在厂商控制台吊销轮换

## 10. 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| `OpenAIError: Missing credentials` | `.env` 缺失或没被加载；确认文件在项目根目录、键名正确，重启服务 |
| 启动时 `hf-mirror.com ... ConnectTimeout` 反复重试 | 模型已在缓存：加 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` |
| `ModuleNotFoundError: torch` / `NameError: name 'nn' is not defined` | 依赖版本冲突。老平台（如 Intel Mac，torch 上限 2.2.2）需钉版本：`numpy==1.26.4 sentence-transformers==3.3.1`；Linux x86_64 直接装 requirements 即可 |
| 前端转圈但没有流式输出 | Nginx 未关 `proxy_buffering`，或经过了会缓冲 SSE 的 CDN/WAF |
| SSE 60s 后断开 | `proxy_read_timeout` 太短，调到 300s |
| 前端 `fetch('/api/...')` 404 | 用了子路径反代——前端是绝对路径，改按域名/端口划分 |
| 回答答非所问 / 检索为空 | 索引未重建：改了 `data/` 后重跑 `01_build_index.py` 并重启 |
| 端口占用 `address already in use` | `lsof -i :8000` 找到旧进程杀掉，或改 `PORT` |
| 中文问题 curl 报 `Invalid HTTP request` | 用 `curl -G --data-urlencode "q=..."`，别把未编码中文拼进 URL |

## 11. 升级更新

```bash
cd /opt/ai-agent-study
git pull
# 依赖有变时：
<proj>/.venv/bin/pip install -r <proj>/requirements.txt
# RAG 文档有变时：
cd 01-rag-knowledge-base-tutorial && .venv/bin/python scripts/01_build_index.py
sudo systemctl restart rag-web agent-web
```
