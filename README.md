# 🎬 直播切片助手 (Live Clipper)

上传直播录像，自动提取字幕，AI 识别精彩片段，一键导出 MP4 剪辑。

## ✨ 功能

- **📤 视频上传** — 支持主流视频格式，拖拽上传
- **📝 字幕提取** — 优先提取内嵌字幕，自动 fallback 到 ASR 语音识别（支持 Whisper API / Qwen DashScope）
- **🤖 AI 分析** — 基于 Claude API 自动识别高光时刻、精彩片段
- **✂️ 片段导出** — ffmpeg 精确剪辑，支持字幕烧录、缩略图生成
- **💬 AI 对话** — 自然语言交互式编辑片段，支持 SSE 流式响应
- **📋 字幕编辑器** — 可视化学幕编辑、导入导出（SRT/VTT/ASS）

## 🏗️ 架构

```
docker compose (5 services)
├── redis           — Celery 消息队列
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
```

### 3. 启动服务

```bash
make up
```

首次启动会自动构建镜像，稍等片刻后访问：

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
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload

# 前端（热重载）
cd frontend && npm install && npm run dev
```

## 📦 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18, TypeScript, Vite, Peaks.js (波形), Konva (画布) |
| 后端 | Python, FastAPI, Celery, SQLite |
| AI | Anthropic Claude API, Whisper API / Qwen DashScope |
| 视频 | ffmpeg, ffprobe |
| 基础设施 | Docker, Redis, Nginx |

## ⚙️ 环境变量

| 变量 | 说明 | 必需 |
|---|---|---|
| `DEFAULT_ASR_PROVIDER` | ASR 提供商: `whisper_api` 或 `qwen` | ✅ |
| `API_KEY_ENCRYPTION_KEY` | Fernet 密钥，加密消息队列中的 API Key | ✅ |
| `ACCESS_TOKEN` | 访问令牌，生产环境必需 | 生产 |
| `QWEN_POLL_TIMEOUT` | Qwen 异步任务轮询超时（秒），默认 600 | |
| `FFMPEG_TIMEOUT` | 单片段导出超时（秒），默认 600 | |
| `REDIS_URL` | Celery broker 地址 | |
| `DATABASE_PATH` | SQLite 数据库路径 | |
| `FONTS_DIR` | 字幕烧录字体目录 | |
| `DEBUG` | 开发模式 | |

## 🔒 安全

- API Key **不落盘** — 数据库和日志中自动脱敏
- Celery 消息队列中 API Key 经 **Fernet 加密**传输
- **路径穿越防护** — 中间件拦截 `..` 和编码绕过
- 字幕 PATCH **仅允许修改文本**，时间戳和片段数不可变

## 📄 License

MIT
