import asyncio
from app.db import async_session
from sqlalchemy import text

async def check():
    async with async_session() as s:
        r = await s.execute(text(
            "SELECT config_key, config_value FROM system_config "
            "WHERE config_key LIKE 'login_rate%' "
            "OR config_key LIKE 'password%' "
            "OR config_key LIKE 'jwt%' "
            "OR config_key LIKE 'register_rate%' "
            "OR config_key LIKE 'session%'"
        ))
        rows = r.fetchall()
        if rows:
            for k, v in rows:
                print(f"  {k} = {v}")
        else:
            print("  暂无记录 — 保存后才会写入 system_config 表")

asyncio.run(check())
