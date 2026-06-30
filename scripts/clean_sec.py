import asyncio
from app.db import async_session
from sqlalchemy import text

async def clean():
    async with async_session() as s:
        await s.execute(text("DELETE FROM system_config WHERE config_key LIKE 'security_%'"))
        await s.commit()
        print("cleaned old keys")

asyncio.run(clean())
