# ITERATION_LOG.md

## 基线

- 测试: 101 passed, 0 failed
- 核心模块: detector, stream_processor, alarm_dedup, rate_limiter, alarm_severity, alarm_broadcaster, metrics, gpu_monitor, health_recorder
- 模型: 3 ONNX (general yolo11l, fire_smoke_v2, helmet_fp16)
- API: stream CRUD, auth, admin, annotations, training, datasets, WebSocket, /metrics, /health

---

## 迭代记录

### Round 1 — auth_service 单元测试
- **任务**: #5 auth_service 单元测试（P0）
- **测试数**: 121 passed (+20)
- **覆盖**: 密码哈希(make_password/check_password)、JWT(create/decode/expired/invalid/wrong-secret)、权限(admin全部/viewer/annotator/operator/未知角色)、b64编码
- **耗时**: ~3min
- **结果**: ✅ 通过
