# SQLAlchemy 集成规范

## 技术栈

| 组件 | 版本 | 说明 |
|------|------|------|
| SQLAlchemy | 2.0+ | ORM + Core |
| aiomysql | 0.2+ | MySQL 异步驱动 |
| MySQL | 5.7+ | 数据库 |

## 目录结构

```
app/
├── db.py                  # 引擎、会话工厂、Base 声明
├── models/                # 所有 ORM 模型（12 张表）
│   ├── __init__.py        # 统一导出
│   ├── alarm_record.py
│   ├── annotation_image.py
│   ├── annotation_box.py
│   ├── dataset.py
│   ├── sys_user.py
│   ├── sys_session.py
│   ├── detection_result.py
│   ├── detection_box.py
│   ├── stream_config.py
│   ├── operation_log.py
│   ├── system_config.py
│   └── training_record.py
└── services/
    └── database.py        # DatabaseService（ORM 查询 + 连接池）
```

## 模型定义规范

### 命名规约

- 表名：单数、全小写、下划线分隔（`alarm_record`）
- 字段名：全小写、下划线分隔（`create_time`）
- 布尔字段：`is_` 前缀（`is_active`、`is_annotated`）
- 主键：`id BIGINT AUTOINCREMENT`
- 审计字段：所有表含 `create_by`、`update_by`、`create_time`、`update_time`
- **无外键约束**：关联字段用普通 BigInteger + index，级联删除由业务代码处理

### 模型模板

```python
from sqlalchemy import Column, BigInteger, String, DateTime, func
from app.db import Base


class XxxRecord(Base):
    __tablename__ = "xxx_record"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # 业务字段...
    create_by = Column(String(64))
    update_by = Column(String(64))
    create_time = Column(DateTime, nullable=False, server_default=func.now())
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
```

### JSON 字段

```python
from sqlalchemy import JSON

alarm_types = Column(JSON, nullable=False, default=["helmet", "fire", "intrusion"])
config = Column(JSON)
```

## 数据库会话管理

### 依赖注入（FastAPI）

```python
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session


@router.get("/xxx")
async def get_xxx(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(XxxRecord))
    return result.scalars().all()
```

### 直接使用

```python
from app.db import async_session


async def my_function():
    async with async_session() as session:
        result = await session.execute(
            select(AlarmRecord).where(AlarmRecord.stream_id == "camera-001")
        )
        records = result.scalars().all()

        # 新增
        record = AlarmRecord(stream_url="rtsp://...", alarm_type="fire")
        session.add(record)
        await session.commit()

        # 删除（业务代码处理级联）
        await session.delete(record)
        await session.commit()
```

## 常用查询

```python
from sqlalchemy import select, and_, func, delete

# 条件过滤
stmt = select(AlarmRecord).where(AlarmRecord.alarm_type == "fire")

# 多条件
stmt = select(AlarmRecord).where(
    and_(AlarmRecord.stream_id == "camera-001", AlarmRecord.confidence > 0.5)
)

# 排序分页
stmt = select(AlarmRecord).order_by(AlarmRecord.create_time.desc()).limit(20).offset(0)

# 聚合
stmt = select(AlarmRecord.alarm_type, func.count(AlarmRecord.id)).group_by(AlarmRecord.alarm_type)

# 关联查询（无外键，手动 join）
stmt = select(DetectionResult, DetectionBox).join(
    DetectionBox, DetectionResult.id == DetectionBox.result_id
)
```

## 迁移策略

项目使用 Alembic 做版本化迁移。

### 常用命令

```bash
# 应用所有迁移
alembic upgrade head

# 生成新迁移（基于模型变更自动对比）
alembic revision --autogenerate -m "描述变更内容"

# 查看迁移历史
alembic history

# 回滚一步
alembic downgrade -1

# 查看当前版本
alembic current
```

### 迁移文件位置

```
alembic/
├── env.py              # 异步引擎配置，导入 models
├── versions/           # 迁移脚本目录
│   └── xxx_init_all_tables.py
└── script.py.mako      # 迁移脚本模板
```

### 工作流程

1. 修改 `app/models/*.py` 中的 ORM 模型
2. 运行 `alembic revision --autogenerate -m "描述"` 生成迁移脚本
3. 检查生成的迁移脚本，必要时手动调整
4. 运行 `alembic upgrade head` 应用迁移
