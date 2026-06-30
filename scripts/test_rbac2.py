import asyncio, httpx, redis.asyncio as aioredis

async def main():
    r = aioredis.from_url('redis://:Redis%40dev2025@192.168.2.100:16377/0', decode_responses=True)
    keys = await r.keys('ratelimit:*')
    if keys:
        await r.delete(*keys)
    await r.aclose()

    async with httpx.AsyncClient(base_url='http://localhost:8000', timeout=10) as c:
        async def login(u, p):
            r = await c.post('/api/v1/auth/login', json={'username': u, 'password': p})
            c.cookies.clear()
            return r.json().get('token') if r.status_code == 200 else None

        tests = [
            ('test_vi', 'Viewer@12', '/api/v1/admin/security-config', 'GET', 403, 'viewer -> security-config: DENY'),
            ('admin', 'admin123', '/api/v1/admin/security-config', 'GET', 200, 'admin -> security-config: ALLOW'),
            ('test_vi', 'Viewer@12', '/api/v1/auth/permissions', 'GET', 200, 'viewer -> permissions: ALLOW'),
            ('test_an', 'Annotator@1', '/api/v1/auth/permissions', 'GET', 200, 'annotator -> permissions: ALLOW'),
        ]
        passed = 0
        for u, p, ep, method, exp, desc in tests:
            t = await login(u, p)
            if not t:
                print(f'  {desc} -> LOGIN FAIL')
                continue
            h = {'Authorization': f'Bearer {t}'}
            r2 = await c.get(ep, headers=h)
            ok = r2.status_code == exp
            if ok:
                passed += 1
            status = 'PASS' if ok else 'FAIL'
            print(f'  {desc} -> {r2.status_code} (expect {exp}) [{status}]')
        print(f'\n  Result: {passed}/4 passed')

asyncio.run(main())
