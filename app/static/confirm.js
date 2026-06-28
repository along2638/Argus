/**
 * 自定义确认弹窗 — 替代原生 confirm()
 * 用法: const ok = await showConfirm('确定删除？')
 */
function showConfirm(message, title) {
    return new Promise(resolve => {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);backdrop-filter:blur(6px);z-index:9999;display:flex;align-items:center;justify-content:center;animation:fadeIn .15s ease';
        overlay.innerHTML = `
            <div style="background:#fff;border-radius:12px;padding:24px 28px;max-width:360px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.12);animation:slideUp .2s ease">
                <div style="font-size:0.88rem;font-weight:600;color:#1c1917;margin-bottom:6px">${title || '请确认'}</div>
                <div style="font-size:0.78rem;color:#78716c;margin-bottom:20px;line-height:1.5">${message}</div>
                <div style="display:flex;gap:8px;justify-content:flex-end">
                    <button id="confirmCancel" style="padding:7px 18px;border:1px solid #e8e6e3;border-radius:8px;background:#fff;color:#78716c;font-size:0.78rem;cursor:pointer;font-family:inherit;transition:0.15s">取消</button>
                    <button id="confirmOk" style="padding:7px 18px;border:none;border-radius:8px;background:#292524;color:#fff;font-size:0.78rem;font-weight:500;cursor:pointer;font-family:inherit;transition:0.15s">确定</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        const ok = () => { overlay.remove(); resolve(true); };
        const cancel = () => { overlay.remove(); resolve(false); };

        overlay.querySelector('#confirmOk').onclick = ok;
        overlay.querySelector('#confirmCancel').onclick = cancel;
        overlay.onclick = e => { if (e.target === overlay) cancel(); };
        overlay.querySelector('#confirmOk').onmouseover = function() { this.style.background = '#44403c'; };
        overlay.querySelector('#confirmOk').onmouseout = function() { this.style.background = '#292524'; };
        overlay.querySelector('#confirmCancel').onmouseover = function() { this.style.borderColor = '#a8a29e'; };
        overlay.querySelector('#confirmCancel').onmouseout = function() { this.style.borderColor = '#e8e6e3'; };

        document.onkeydown = e => { if (e.key === 'Escape') cancel(); };
    });
}

if (!document.getElementById('confirm-style')) {
    const s = document.createElement('style');
    s.id = 'confirm-style';
    s.textContent = '@keyframes fadeIn{from{opacity:0}to{opacity:1}}@keyframes slideUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}';
    document.head.appendChild(s);
}
