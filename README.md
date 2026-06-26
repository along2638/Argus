# Argus — 智能监控告警系统

实时视频监控告警系统，支持 RTSP/RTMP 流接入、YOLOv11 多目标检测、Redis 去重、MySQL 持久化、MinIO 图片存储。

## 功能特性

- **实时流处理**: RTSP/RTMP 监控流接入，指数退避重连
- **智能检测**: YOLOv11 ONNX 推理，支持通用/火灾烟雾/安全帽三模型
- **目标跟踪**: ByteTrack 实时跟踪与告警去重
- **告警类型**: 安全帽、火灾烟雾、入侵检测
- **图片检测**: 上传图片检测，历史记录查看
- **手动标注**: 在线标注工具，YOLO 格式输出
- **用户认证**: JWT + PBKDF2-SHA256，角色权限控制
- **异步架构**: FastAPI + SQLAlchemy + aiomysql

## 技术栈

| 模块 | 技术 |
|------|------|
| Web 框架 | FastAPI (async) |
| ORM | SQLAlchemy 2.0 + aiomysql |
| 数据库 | MySQL 5.7+ |
| 检测引擎 | YOLOv11 ONNX (GPU/CPU) |
| 目标跟踪 | ByteTrack (supervision) |
| 流媒体拉流 | PyAV (RTSP/RTMP) |
| 任务队列 | ARQ + Redis |
| 对象存储 | MinIO |
| 认证 | JWT + PBKDF2-SHA256 |
| 数据库迁移 | Alembic |
| 日志 | structlog |
| 前端 | 原生 HTML/CSS/JS |

## 快速开始

### 1. 安装依赖

```bash
pip install -e ".[dev]"
# 或
uv pip install -e ".[dev]"
```

### 2. 配置环境

```bash
cp .env.example .env
# 编辑 .env 填写数据库、Redis、MinIO 连接信息
```

### 3. 数据库迁移

```bash
alembic upgrade head
```

### 4. 启动服务

```bash
# 开发模式
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Docker Compose
docker compose up -d
```

### 5. 访问

- 前端面板: http://localhost:8000
- API 文档: http://localhost:8000/docs
- 默认账号: admin / admin123

## 项目结构

```
app/
├── main.py              # FastAPI 入口，中间件，标注 API
├── config.py            # Settings 单例
├── db.py                # SQLAlchemy 引擎、会话工厂
├── api/v1/
│   ├── auth.py          # 认证 API（登录/注册/用户管理）
│   └── stream.py        # 流管理 + 图片检测 API
├── core/
│   ├── detector.py      # MultiModelDetector，3 个 ONNX 模型
│   ├── stream_processor.py  # StreamProcessor + StreamManager
│   └── alarm_dedup.py   # Redis 告警去重
├── models/              # 11 个 SQLAlchemy ORM 模型
├── services/
│   ├── auth_service.py  # JWT + PBKDF2 认证逻辑
│   ├── database.py      # DatabaseService 兼容层
│   ├── minio_client.py  # MinIO 上传
│   └── worker_tasks.py  # ARQ 异步任务
├── utils/
│   └── logger.py        # structlog 日志
└── static/              # 前端页面
    ├── index.html       # 监控流管理主页
    ├── login.html       # 登录页
    ├── detect.html      # 图片检测页
    └── annotate.html    # 手动标注页
```

## 数据库表（11 张）

| 表名 | 说明 |
|------|------|
| alarm_record | 告警记录 |
| annotation_image | 标注图片 |
| annotation_box | 标注框 (YOLO 格式) |
| dataset | 数据集配置 |
| sys_user | 用户 |
| detection_result | 图片检测结果 |
| detection_box | 检测框 |
| stream_config | 监控流配置 |
| operation_log | 操作日志 |
| system_config | 系统配置 |
| training_record | 训练记录 |

## 命名规约

- 表名单数、全小写、下划线分隔
- 布尔字段 `is_` 前缀
- 审计字段：`create_by`、`update_by`、`create_time`、`update_time`
- 索引 `idx_` 前缀
- 无外键约束，业务代码解耦
