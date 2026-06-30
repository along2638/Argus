import asyncio, httpx, redis.asyncio as aioredis

async def main():
    r = aioredis.from_url('redis://:Redis%40dev2025@192.168.2.100:16377/0', decode_responses=True)
    keys = await r.keys('ratelimit:*')
    if keys:
        await r.delete(*keys)
    await r.aclose()

    async with httpx.AsyncClient(base_url='http://localhost:8000', timeout=10) as c:
        r = await c.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'admin123'})
        c.cookies.clear()
        if r.status_code != 200:
            print('admin login failed'); return
        h = {'Authorization': f'Bearer {r.json()["token"]}'}

        r2 = await c.get('/api/v1/auth/users', headers=h)
        print('Users:')
        for u in r2.json().get('users', []):
            print(f"  {u['username']:15s} role={u['role']:12s} active={u['is_active']}")

        for uname, pwd in [('test_vi', 'Viewer@12'), ('test_an', 'Annotator@1')]:
            r3 = await c.post('/api/v1/auth/login', json={'username': uname, 'password': pwd})
            c.cookies.clear()
            print(f"  {uname} login: {r3.status_code} {r3.json().get('detail', 'OK')}")

asyncio.run(main())
