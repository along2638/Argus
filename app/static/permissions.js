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
 * 检查是否有权限执行某个操作，无权限则提示
 */
function requirePermission(perm, action) {
    if (!hasPermission(perm)) {
        if (typeof showNotification === 'function') {
            showNotification(`无权${action || '执行此操作'}`, 'error');
        }
        return false;
    }
    return true;
}
