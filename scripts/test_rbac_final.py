"""RBAC 权限系统最终测试 — 复用 token 避免频率限制。"""
import asyncio
import httpx
import redis.asyncio as aioredis

BASE = "http://localhost:8000"

async def clear_rate_limit():
    r = aioredis.from_url('redis://:Redis%40dev2025@192.168.2.100:16377/0', decode_responses=True)
    keys = await r.keys('ratelimit:*')
    if keys:
        await r.delete(*keys)
    await r.aclose()

async def login(c, username, password):
    r = await c.post('/api/v1/auth/login', json={'username': username, 'password': password})
    c.cookies.clear()
    if r.status_code == 200:
        return r.json()['token']
    print(f'  login {username} failed: {r.status_code}')
    return None

async def main():
    await clear_rate_limit()

    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        # 预登录所有用户，拿到 token
        tokens = {}
        for uname, pwd in [('admin', 'admin123'), ('test_op', 'Operator@1'), ('test_an', 'Annotator@1'), ('test_vi', 'Viewer@12')]:
            t = await login(c, uname, pwd)
            if t:
                tokens[uname] = t

        if 'admin' not in tokens:
            print('admin login failed, abort'); return

        ah = {'Authorization': f'Bearer {tokens["admin"]}'}

        # 确保用户存在
        r = await c.get('/api/v1/auth/users', headers=ah)
        existing = {u['username'] for u in r.json().get('users', [])}
        for uname, pwd, role in [('test_op', 'Operator@1', 'operator'), ('test_an', 'Annotator@1', 'annotator'), ('test_vi', 'Viewer@12', 'viewer')]:
            if uname not in existing:
                await c.post('/api/v1/auth/register', json={'username': uname, 'password': pwd, 'display_name': uname})
        r = await c.get('/api/v1/auth/users', headers=ah)
        for u in r.json().get('users', []):
            if u['username'].startswith('test_') and u['role'] != {'test_op': 'operator', 'test_an': 'annotator', 'test_vi': 'viewer'}.get(u['username']):
                target = {'test_op': 'operator', 'test_an': 'annotator', 'test_vi': 'viewer'}[u['username']]
                await c.put(f'/api/v1/auth/users/{u["id"]}/role', json={'role': target}, headers=ah)

        print('=== RBAC Permission Test ===\n')

        # 用预登录的 token 测试
        tests = [
            ('test_vi',  '/api/v1/auth/users',             'GET',  403, 'viewer    -> user mgmt      = DENY'),
            ('test_op',  '/api/v1/auth/users',             'GET',  403, 'operator  -> user mgmt      = DENY'),
            ('admin',    '/api/v1/auth/users',             'GET',  200, 'admin     -> user mgmt      = ALLOW'),
            ('test_vi',  '/api/v1/admin/logs',             'GET',  200, 'viewer    -> view logs      = ALLOW'),
            ('test_vi',  '/api/v1/admin/security-config',  'GET',  403, 'viewer    -> security cfg   = DENY'),
            ('admin',    '/api/v1/admin/security-config',  'GET',  200, 'admin     -> security cfg   = ALLOW'),
            ('test_vi',  '/api/v1/auth/permissions',       'GET',  200, 'viewer    -> view perms     = ALLOW'),
            ('test_an',  '/api/v1/auth/permissions',       'GET',  200, 'annotator -> view perms     = ALLOW'),
            ('test_op',  '/api/v1/admin/security-config',  'GET',  403, 'operator  -> security cfg   = DENY'),
            ('test_an',  '/api/v1/admin/logs',             'GET',  200, 'annotator -> view logs      = ALLOW'),
        ]

        passed = 0
        for uname, ep, method, exp, desc in tests:
            t = tokens.get(uname)
            if not t:
                print(f'  {desc} -> NO TOKEN'); continue
            h = {'Authorization': f'Bearer {t}'}
            r2 = await c.get(ep, headers=h) if method == 'GET' else await c.post(ep, headers=h, json={})
            ok = r2.status_code == exp
            if ok:
                passed += 1
            mark = 'PASS' if ok else 'FAIL'
            print(f'  {desc:50s} {r2.status_code:>3d} (expect {exp}) [{mark}]')

        print(f'\n  Result: {passed}/{len(tests)} passed')

asyncio.run(main())
