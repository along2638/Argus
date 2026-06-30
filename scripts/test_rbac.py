"""RBAC 权限系统测试脚本。"""
import asyncio
import httpx

BASE = "http://localhost:8000"

async def login(c, username, password):
    r = await c.post("/api/v1/auth/login", json={"username": username, "password": password})
    c.cookies.clear()
    if r.status_code == 200:
        return r.json()["token"]
    return None

async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        # 1. admin 登录
        token = await login(c, "admin", "admin123")
        if not token:
            print("admin 登录失败"); return
        ah = {"Authorization": f"Bearer {token}"}
        print("[1] admin 登录 OK")

        # 2. 清理 + 创建测试用户
        r = await c.get("/api/v1/auth/users", headers=ah)
        for u in r.json().get("users", []):
            if u["username"].startswith("test_"):
                await c.delete(f"/api/v1/auth/users/{u['id']}", headers=ah)

        for uname, pwd, display in [("test_op", "Operator@1", "操作员"), ("test_an", "Annotator@1", "标注员"), ("test_vi", "Viewer@12", "观察者")]:
            await c.post("/api/v1/auth/register", json={"username": uname, "password": pwd, "display_name": display})

        r = await c.get("/api/v1/auth/users", headers=ah)
        role_map = {"test_op": "operator", "test_an": "annotator", "test_vi": "viewer"}
        for u in r.json().get("users", []):
            if u["username"] in role_map:
                await c.put(f"/api/v1/auth/users/{u['id']}/role", json={"role": role_map[u["username"]]}, headers=ah)
        print("[2] 测试用户创建完成")

        # 3. 打印用户和权限
        r = await c.get("/api/v1/auth/users", headers=ah)
        print("\n  用户列表:")
        for u in r.json().get("users", []):
            if u["username"].startswith("test_") or u["username"] == "admin":
                print(f"    {u['username']:12s} role={u['role']}")

        r = await c.get("/api/v1/auth/permissions", headers=ah)
        print("\n  权限配置:")
        for role, perms in r.json().get("roles", {}).items():
            print(f"    {role:12s}: {', '.join(perms) if perms else '(默认)'}")

        # 4. 权限测试 — 用 GET 端点避免 body 校验问题
        print("\n[3] 权限拦截测试:")
        tests = [
            # (用户, 密码, 端点, 方法, 期望码, 说明)
            ("test_vi", "Viewer@12",  "/api/v1/auth/users",       "GET",  403, "viewer→用户管理=拒绝"),
            ("test_op", "Operator@1", "/api/v1/auth/users",       "GET",  403, "operator→用户管理=拒绝"),
            ("admin",   "admin123",   "/api/v1/auth/users",       "GET",  200, "admin→用户管理=通过"),
            ("test_vi", "Viewer@12",  "/api/v1/admin/logs",       "GET",  200, "viewer→查看日志=通过"),
            ("test_vi", "Viewer@12",  "/api/v1/admin/security-config", "GET", 403, "viewer→安全配置=拒绝"),
            ("admin",   "admin123",   "/api/v1/admin/security-config", "GET", 200, "admin→安全配置=通过"),
            ("test_vi", "Viewer@12",  "/api/v1/auth/permissions", "GET",  200, "viewer→查看权限=通过"),
            ("test_an", "Annotator@1","/api/v1/auth/permissions", "GET",  200, "annotator→查看权限=通过"),
        ]
        passed = 0
        for uname, pwd, ep, method, exp, desc in tests:
            t = await login(c, uname, pwd)
            if not t:
                print(f"  {desc:40s} → 登录失败"); continue
            h = {"Authorization": f"Bearer {t}"}
            r2 = await c.get(ep, headers=h) if method == "GET" else await c.post(ep, headers=h, json={})
            ok = r2.status_code == exp
            if ok: passed += 1
            mark = "PASS" if ok else "FAIL"
            print(f"  {desc:40s} → {r2.status_code} (期望{exp}) [{mark}]")

        print(f"\n  结果: {passed}/{len(tests)} 通过")

asyncio.run(main())
