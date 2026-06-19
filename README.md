# 🎬 FasterClip — AI 驱动的直播切片助手

上传直播录像，自动提取字幕，AI 识别精彩片段，一键导出 MP4 剪辑。

## 💡 亮点

**用自然语言做视频切片。** 上传视频后，你可以像和人对话一样告诉 AI 你想要什么：

> "帮我把 3 分 20 秒到 5 分钟那段剪出来，加上字幕"
> "用 qwen 重新识别一下字幕，识别效果不太好"
> "找一下聊到产品发布的片段，最多 3 个"
> "这几段字幕太长了，帮我拆分一下"
> "删掉第三个片段，把剩下的都导出"

AI 不只是回话——它手上有一组可记录、可约束的工具，可以直接操作你的项目：跑 ASR、编辑字幕时间轴、搜索内容、分析高光、导出 MP4、调整样式。每次工具调用都会经过任务状态校验，并写入 `tool_runs` 记录，便于排查和审计。

## ✨ 功能

- **📤 视频上传** — 支持主流视频格式，拖拽上传，浏览器内预览
- **📝 字幕提取** — 优先提取内嵌字幕，自动 fallback 到 ASR 语音识别（Whisper / Qwen / SenseVoice）
- **🤖 AI 分析** — LLM自动识别高光时刻，支持自定义关注点和时间范围
- **✂️ 片段导出** — ffmpeg 精确剪辑，支持字幕烧录、缩略图生成、多种字幕样式预设
- **💬 AI 对话** — 自然语言交互，SSE 流式响应，AI 可直接操作字幕和片段
- **📋 字幕编辑器** — 可视化字幕编辑，拖拽调整时间轴，波形图辅助定位
- **🔤 智能分行** — 词级时间轴驱动，标点优先断句，自动生成节奏自然的字幕行

## 🗺️ Roadmap

**当前阶段：打磨 Agent 工具链。** 持续优化 Agent 工具的准确性和覆盖范围，同时加强工具调用的记录、状态约束和可调试性——让 AI 更精准地理解用户意图，处理更多边界场景，工具之间的协作更流畅。

**未来目标：用户自定义工作流。** 不再局限于单个指令。用户可以定义自己的处理流水线：先跑 ASR → 按关键词搜索 → 自动导出匹配片段 → 套用指定字幕样式。像搭积木一样组合工具，一键复现你的切片流程。

## 🏗️ 架构

```
docker compose (6 services)
├── mysql           — 主业务数据库（tasks / tool_runs / schema_version）
├── redis           — Celery 消息队列 + 限流存储
├── backend         — FastAPI (uvicorn, :8000)
├── celery-worker   — 异步视频处理 + AI 导出
├── celery-beat     — 定时清理过期任务
└── frontend        — Vite + React (dev server :3000)
```

### 处理管线

```
上传 → 字幕提取 → LLM 分析 → ffmpeg 导出 → 完成
         ↓            ↓           ↓
    断点续跑      片段预览    缩略图 + 字幕烧录
```

### Agent 工具调用

```
ChatService → WorkflowRuntime 状态校验 → ToolExecutor 执行工具 → MySQL tool_runs 审计记录
```

- `WorkflowRuntime` 在执行前检查任务是否已有字幕、片段或导出状态，避免非法工具调用。
- `ToolExecutor` 统一处理工具查找、参数过滤、临时错误重试和异常包装。
- `tool_runs` 记录每次工具调用的 `running / success / error / rejected` 生命周期，输入输出会先脱敏。

### 持久化层

生产和 Docker 本地联调默认使用 MySQL。后端通过 `backend/app/database.py` 的轻量适配层访问数据库，业务模型不直接依赖具体驱动：

- `DATABASE_ENGINE=mysql`：主路径，使用 `pymysql` 连接 MySQL。
- `DATABASE_ENGINE=sqlite`：仅作为本地开发和测试 fallback。
- `schema_version` 当前版本为 `6`，`init_db()` 可重复执行。
- `tasks` 保存任务状态、配置、字幕/聊天版本号和片段 JSON；API key 会在入库前剔除。
- `tool_runs` 保存工具调用审计记录，并在 MySQL 下创建 `tool_runs(task_id, started_at)` 索引。
- `version`、`transcript_version`、`chat_version` 继续使用条件 `UPDATE` 做乐观锁。

## 🚀 快速开始

### 前置要求

- Docker & Docker Compose
- Anthropic API Key（用于 LLM 分析）
- ASR API Key（Whisper API 或 Qwen DashScope，二选一）

### 1. 克隆项目

```bash
git clone https://github.com/JiangQianJiang/faster-clip.git
cd faster-clip
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入必要配置：

```env
# ASR 提供商（必需）
DEFAULT_ASR_PROVIDER=qwen

# 加密密钥（必需，用于保护 API Key 在消息队列中的传输）
API_KEY_ENCRYPTION_KEY=<生成方式见 .env.example>

# 访问令牌（生产环境必需，至少 32 字符）
ACCESS_TOKEN=<随机生成>

# MySQL（Docker 默认值可直接本地使用，生产请换强密码）
MYSQL_DATABASE=fasterclip
MYSQL_USER=fasterclip
MYSQL_PASSWORD=<随机密码>
MYSQL_ROOT_PASSWORD=<随机密码>
DATABASE_ENGINE=mysql
DATABASE_URL=mysql+pymysql://fasterclip:<随机密码>@mysql:3306/fasterclip
```

### 3. 启动服务

```bash
make up
```

首次启动会自动构建镜像并启动 MySQL、Redis、backend、celery-worker、celery-beat 和 frontend。MySQL 数据会保存在 Docker volume `mysql-data`，容器重启不会丢失。稍等片刻后访问：

- **前端**: http://localhost:3000
- **后端 API**: http://localhost:8000/api/health

### 4. 使用

1. 打开 http://localhost:3000
2. 在配置面板填入你的 Anthropic API Key 和 ASR API Key（不落盘，仅内存保存）
3. 上传视频文件
4. 等待自动处理完成，浏览和导出精彩片段

## 🛠️ 开发

```bash
make help          # 查看所有命令

make up            # 启动全部服务
make down          # 停止全部服务
make build         # 重新构建镜像
make logs          # 查看日志

make test          # 运行全部测试
make lint          # 代码检查
make clean         # 清空数据目录
```

### 本地开发（不通过 Docker）

```bash
# 后端
cd backend
pip install -r requirements.txt
DATABASE_ENGINE=sqlite DATABASE_URL=sqlite:///data/live-clipper.db uvicorn app.main:app --reload

# 前端（热重载）
cd frontend && npm install && npm run dev
```

SQLite 仅作为本地开发/测试 fallback。生产和 Docker 本地联调路径使用 MySQL：

```bash
docker compose up mysql redis
cd backend
DATABASE_ENGINE=mysql \
DATABASE_URL=mysql+pymysql://fasterclip:password@127.0.0.1:3306/fasterclip \
uvicorn app.main:app --reload
```

MySQL 集成测试默认不会在 CI 中运行。启动本地 MySQL 后可显式执行：

```bash
cd backend
MYSQL_TEST_DATABASE_URL=mysql+pymysql://fasterclip:password@127.0.0.1:3306/fasterclip \
python3 -m pytest tests/test_database_core.py tests/test_database_adapter.py -m mysql -v
```

### 数据库检查

```bash
docker compose exec mysql mysql -ufasterclip -p fasterclip
```

进入 MySQL 后可检查：

```sql
SHOW TABLES;
SELECT version FROM schema_version;
SHOW INDEX FROM tool_runs;
```

## 📦 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18, TypeScript, Vite, Peaks.js (波形), Konva (画布) |
| 后端 | Python, FastAPI, Celery, MySQL（SQLite local/test fallback） |
| AI | Anthropic Claude API, Whisper API / Qwen DashScope |
| 视频 | ffmpeg, ffprobe |
| 基础设施 | Docker, MySQL, Redis, Nginx |

## ⚙️ 环境变量

| 变量 | 说明 | 必需 |
|---|---|---|
| `DEFAULT_ASR_PROVIDER` | ASR 提供商: `whisper_api` 或 `qwen` | ✅ |
| `API_KEY_ENCRYPTION_KEY` | Fernet 密钥，加密消息队列中的 API Key | ✅ |
| `ACCESS_TOKEN` | 访问令牌，生产环境必需 | 生产 |
| `QWEN_POLL_TIMEOUT` | Qwen 异步任务轮询超时（秒），默认 600 | |
| `FFMPEG_TIMEOUT` | 单片段导出超时（秒），默认 600 | |
| `REDIS_URL` | Celery broker 地址 | |
| `DATABASE_ENGINE` | 数据库引擎: `mysql` 或 `sqlite`，生产默认 `mysql` | |
| `DATABASE_URL` | 主数据库连接串，例如 `mysql+pymysql://fasterclip:password@mysql:3306/fasterclip` | |
| `DATABASE_PATH` | SQLite fallback 路径，仅 local/test 使用 | |
| `MYSQL_DATABASE` | Docker MySQL 初始化数据库名 | Docker |
| `MYSQL_USER` | Docker MySQL 应用用户名 | Docker |
| `MYSQL_PASSWORD` | Docker MySQL 应用用户密码 | Docker |
| `MYSQL_ROOT_PASSWORD` | Docker MySQL root 密码 | Docker |
| `FONTS_DIR` | 字幕烧录字体目录 | |
| `DEBUG` | 开发模式 | |

## 🔒 安全

- API Key **不落盘** — 数据库、`tool_runs`、聊天历史和日志中自动脱敏
- Celery 消息队列中 API Key 经 **Fernet 加密**传输
- **路径穿越防护** — 中间件拦截 `..` 和编码绕过
- 字幕 PATCH 使用 `transcript_version` 乐观锁，避免并发编辑覆盖

## 📄 License

MIT
