.PHONY: up down build restart ps logs logs-backend logs-worker logs-beat logs-frontend test test-backend test-one test-frontend test-e2e build-frontend lint lint-backend lint-frontend verify clean reset help

# ── 服务管理 ──────────────────────────────────────────────

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

restart: down up

ps:
	docker compose ps

# ── 日志 ─────────────────────────────────────────────────

logs:
	docker compose logs -f --tail=50

logs-backend:
	docker compose logs -f --tail=50 backend

logs-worker:
	docker compose logs -f --tail=50 celery-worker

logs-beat:
	docker compose logs -f --tail=50 celery-beat

logs-frontend:
	docker compose logs -f --tail=50 frontend

# ── 测试 ─────────────────────────────────────────────────

test: test-backend test-frontend

test-backend:
	cd backend && python3 -m pytest tests/ -v

test-one:
	cd backend && python3 -m pytest tests/ -k "$(t)" -v

test-frontend:
	cd frontend && npx vitest run

test-e2e:
	cd frontend && npx playwright test

build-frontend:
	cd frontend && npm run build

# ── 代码检查 ────────────────────────────────────────────

lint: lint-backend lint-frontend

lint-backend:
	cd backend && python3 -m ruff check .

lint-frontend:
	cd frontend && npx tsc --noEmit

# ── 完整验证 ────────────────────────────────────────────

verify: lint test test-e2e
	docker compose config --quiet
	@echo "验证完成: lint + test + test-e2e + compose config 均通过"

# ── 清理 ─────────────────────────────────────────────────

clean:
	rm -rf data/videos/* data/output/*

reset: down clean
	docker compose build --no-cache
	docker compose up -d

# ── 帮助 ─────────────────────────────────────────────────

help:
	@echo "live-clipper 开发命令"
	@echo ""
	@echo "  服务管理"
	@echo "    make up            启动所有服务"
	@echo "    make down          停止所有服务"
	@echo "    make build         重新构建镜像"
	@echo "    make restart       重启所有服务"
	@echo "    make ps            查看容器状态"
	@echo ""
	@echo "  日志"
	@echo "    make logs          查看所有日志（跟随）"
	@echo "    make logs-backend  查看后端日志"
	@echo "    make logs-worker   查看 worker 日志"
	@echo "    make logs-frontend 查看前端日志"
	@echo ""
	@echo "  测试"
	@echo "    make test          运行全部测试"
	@echo "    make test-backend  运行后端测试"
	@echo "    make test-one t=search_transcript  运行匹配关键字的测试"
	@echo ""
	@echo "  代码检查"
	@echo "    make lint          运行全部检查"
	@echo "    make lint-backend  后端 Ruff 检查"
	@echo "    make lint-frontend TypeScript 类型检查"
	@echo ""
	@echo "  清理"
	@echo "    make clean         清空数据目录"
	@echo "    make reset         完全重建（清数据 + 清缓存 + 重建镜像）"
