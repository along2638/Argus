# FEATURE_BACKLOG.md

## P0 — 高优先级（安全/稳定性）

| # | 功能 | 来源 | 状态 | 文件 |
|---|------|------|------|------|
| 1 | 登录暴力破解防护 | AI发现 | ✅ DONE | app/core/rate_limiter.py |
| 2 | 告警升级机制 | AI发现 | ✅ DONE | app/core/alarm_severity.py |
| 3 | CSRF 防护 | AI发现 | OPEN | - |
| 4 | 密码复杂度策略 | AI发现 | ✅ DONE | app/services/auth_service.py |
| 5 | auth_service 单元测试 | AI发现 | ✅ DONE | tests/test_auth_service.py |

## P1 — 中优先级（业务价值）

| # | 功能 | 来源 | 状态 | 文件 |
|---|------|------|------|------|
| 6 | WebSocket 实时推送 | AI发现 | ✅ DONE | app/core/alarm_broadcaster.py |
| 7 | Prometheus 指标 | AI发现 | ✅ DONE | app/core/metrics.py |
| 8 | GPU 显存监控 | AI发现 | ✅ DONE | app/core/gpu_monitor.py |
| 9 | 流健康持久化 | AI发现 | ✅ DONE | app/core/health_recorder.py |
| 10 | ROI 区域检测 | AI发现 | ✅ DONE | app/core/stream_processor.py |
| 11 | 邮件通知 | AI发现 | ✅ DONE | app/core/email_notifier.py |
| 12 | 定时巡检调度 | AI发现 | ✅ DONE | app/core/schedule_checker.py |

## P2 — 低优先级（锦上添花）

| # | 功能 | 来源 | 状态 | 文件 |
|---|------|------|------|------|
| 13 | 暗色主题 | AI发现 | ✅ DONE | app/static/theme.js |
| 14 | 批量视频分析报告 | AI发现 | ✅ DONE | app/core/batch_analyzer.py |
| 15 | 标注版本控制 | AI发现 | OPEN | - |
| 16 | operation_log 测试 | AI发现 | ✅ DONE | tests/test_operation_log_service.py |
