/**
 * 前端权限检查工具 — 基于用户角色控制 UI 元素可见性
 */
function getUserPermissions() {
    try {
        const user = JSON.parse(localStorage.getItem('user') || '{}');
        return user.permissions || [];
    } catch {
        return [];
    }
}

function getUserRole() {
    try {
        const user = JSON.parse(localStorage.getItem('user') || '{}');
        return user.role || '';
    } catch {
        return '';
    }
}

function hasPermission(perm) {
    return getUserPermissions().includes(perm);
}

/**
 * 根据权限隐藏/显示元素
 * 用法: applyPermissions({
 *   '#btnManage': 'manage_user',
 *   '#btnDelete': 'manage_alarm',
 *   '.admin-only': 'admin',
 * })
 */
function applyPermissions(map) {
    for (const [selector, perm] of Object.entries(map)) {
        const els = document.querySelectorAll(selector);
        const allowed = hasPermission(perm);
        els.forEach(el => {
            el.style.display = allowed ? '' : 'none';
            if (!allowed) el.disabled = true;
        });
    }
}

/**
 * 初始化页面权限控制（在 DOMContentLoaded 后调用）
 */
function initPagePermissions() {
    const role = getUserRole();
    const perms = getUserPermissions();

    // 通用规则：管理员可见全部，其他人根据权限控制
    if (role === 'admin') return; // admin 不限制

    // 隐藏/禁用需要特定权限的元素
    applyPermissions({
        '[data-perm]': null, // 由各元素的 data-perm 属性决定
    });

    // 根据 data-perm 属性控制
    document.querySelectorAll('[data-perm]').forEach(el => {
        const required = el.getAttribute('data-perm');
        if (!perms.includes(required)) {
            el.style.display = 'none';
            el.disabled = true;
        }
    });
}

/**
 * 检查是否有权限执行某个操作，无权限则弹出居中提示
 */
function requirePermission(perm, action) {
    if (!hasPermission(perm)) {
        showPermDenied(action || '执行此操作');
        return false;
    }
    return true;
}

/**
 * 居中权限不足提示弹窗
 */
function showPermDenied(action) {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);backdrop-filter:blur(6px);z-index:9999;display:flex;align-items:center;justify-content:center;animation:fadeIn .15s ease';
    overlay.innerHTML = `
        <div style="background:#fff;border-radius:12px;padding:28px 32px;max-width:380px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.12);animation:slideUp .2s ease;text-align:center">
            <div style="width:48px;height:48px;border-radius:50%;background:#fef2f2;display:flex;align-items:center;justify-content:center;margin:0 auto 16px">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
            </div>
            <div style="font-size:1rem;font-weight:600;color:#1c1917;margin-bottom:6px">权限不足</div>
            <div style="font-size:0.82rem;color:#78716c;margin-bottom:20px">您没有「${action}」的权限，请联系管理员</div>
            <button onclick="this.closest('div[style]').parentElement.remove()" style="padding:8px 28px;border:none;border-radius:8px;background:#292524;color:#fff;font-size:0.82rem;font-weight:500;cursor:pointer;font-family:inherit;transition:0.15s">知道了</button>
        </div>
    `;
    document.body.appendChild(overlay);
    overlay.onclick = e => { if (e.target === overlay) overlay.remove(); };
    setTimeout(() => { if (overlay.parentElement) overlay.remove(); }, 5000);
}

// 注入动画样式
if (!document.getElementById('perm-style')) {
    const s = document.createElement('style');
    s.id = 'perm-style';
    s.textContent = '@keyframes fadeIn{from{opacity:0}to{opacity:1}}@keyframes slideUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}';
    document.head.appendChild(s);
}
