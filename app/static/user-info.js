/**
 * 共享用户信息下拉菜单组件
 * 用法：在页面 <div class="topbar-right"> 中插入 placeholder：
 *   <div id="userInfoSlot"></div>
 * 然后引入此脚本：  <script src="/static/user-info.js"></script>
 */
(function () {
    const CSS = `
.user-dropdown{position:relative}
.user-trigger{display:flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid var(--border);border-radius:var(--radius);background:var(--accent-soft);cursor:pointer;transition:var(--transition);font-family:inherit;font-size:0.78rem;color:var(--ink)}
.user-trigger:hover{border-color:var(--ink-faint)}
.user-avatar{width:26px;height:26px;border-radius:50%;background:var(--ink);color:var(--bg);display:flex;align-items:center;justify-content:center;font-size:0.7rem;font-weight:600;flex-shrink:0}
.user-menu{position:absolute;top:calc(100% + 6px);right:0;min-width:180px;background:var(--bg-card-solid,#fff);border:1px solid var(--border);border-radius:var(--radius-md,12px);box-shadow:0 8px 24px rgba(0,0,0,0.1);z-index:100;display:none;overflow:hidden}
.user-dropdown.open .user-menu{display:block}
.user-menu-header{padding:14px 16px;display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--border)}
.user-avatar-lg{width:36px;height:36px;border-radius:50%;background:var(--ink);color:var(--bg);display:flex;align-items:center;justify-content:center;font-size:0.85rem;font-weight:600;flex-shrink:0}
.user-menu-name{font-size:0.85rem;font-weight:600}
.user-menu-role{font-size:0.7rem;color:var(--ink-muted,#78716c)}
.user-menu-divider{height:1px;background:var(--border);margin:4px 0}
.user-menu-item{display:flex;align-items:center;gap:8px;padding:9px 16px;font-size:0.8rem;color:var(--ink-light,#44403c);cursor:pointer;transition:var(--transition);text-decoration:none}
.user-menu-item:hover{background:var(--accent-soft);color:var(--ink)}
.user-menu-item.danger{color:var(--danger,#dc2626)}
.user-menu-item.danger:hover{background:var(--danger-bg,#fef2f2)}
`;

    const style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);

    const ROLES = { admin: '管理员', operator: '操作员', annotator: '标注员', viewer: '观察者' };

    function render() {
        let user = {};
        try { user = JSON.parse(localStorage.getItem('user') || '{}'); } catch (e) {}
        if (!user.username) return;

        const name = user.display_name || user.username;
        const initial = name.charAt(0).toUpperCase();
        const role = ROLES[user.role] || user.role || '';

        const html = `
<div class="user-dropdown" id="userDropdown">
    <button class="user-trigger" onclick="document.getElementById('userDropdown').classList.toggle('open')">
        <div class="user-avatar">${initial}</div>
        <span>${name}</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
    </button>
    <div class="user-menu">
        <div class="user-menu-header">
            <div class="user-avatar-lg">${initial}</div>
            <div><div class="user-menu-name">${name}</div><div class="user-menu-role">${role}</div></div>
        </div>
        <div class="user-menu-divider"></div>
        <a class="user-menu-item" onclick="if(typeof showProfileModal==='function')showProfileModal()">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            个人信息
        </a>
        <div class="user-menu-divider"></div>
        <a class="user-menu-item danger" onclick="doLogout()">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16,17 21,12 16,7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
            退出登录
        </a>
    </div>
</div>`;

        const slot = document.getElementById('userInfoSlot');
        if (slot) slot.innerHTML = html;
    }

    document.addEventListener('click', function (e) {
        const dd = document.getElementById('userDropdown');
        if (dd && !e.target.closest('.user-dropdown')) dd.classList.remove('open');
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', render);
    } else {
        render();
    }
})();
