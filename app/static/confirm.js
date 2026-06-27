/**
 * 自定义确认弹窗 — 替代原生 confirm()
 * 用法: const ok = await showConfirm('确定删除？')
 */
function showConfirm(message) {
    return new Promise(resolve => {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);backdrop-filter:blur(8px);z-index:9999;display:flex;align-items:center;justify-content:center;animation:fadeIn .2s ease';
        overlay.innerHTML = `
            <div style="background:#fff;border-radius:16px;padding:28px 32px;max-width:380px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.25);animation:slideUp .25s ease">
                <div style="font-size:0.92rem;font-weight:600;color:#1a1a1a;margin-bottom:8px">请确认</div>
                <div style="font-size:0.84rem;color:#8a8580;margin-bottom:24px;line-height:1.5">${message}</div>
                <div style="display:flex;gap:10px;justify-content:flex-end">
                    <button id="confirmCancel" style="padding:8px 20px;border:1px solid rgba(0,0,0,0.06);border-radius:999px;background:transparent;color:#8a8580;font-size:0.82rem;cursor:pointer;font-family:inherit;transition:0.2s">取消</button>
                    <button id="confirmOk" style="padding:8px 20px;border:none;border-radius:999px;background:#1a1a1a;color:#f5f0eb;font-size:0.82rem;font-weight:500;cursor:pointer;font-family:inherit;transition:0.2s">确定</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        const ok = () => { overlay.remove(); resolve(true); };
        const cancel = () => { overlay.remove(); resolve(false); };

        overlay.querySelector('#confirmOk').onclick = ok;
        overlay.querySelector('#confirmCancel').onclick = cancel;
        overlay.onclick = e => { if (e.target === overlay) cancel(); };
        overlay.querySelector('#confirmOk').onmouseover = function() { this.style.background = '#333'; };
        overlay.querySelector('#confirmOk').onmouseout = function() { this.style.background = '#1a1a1a'; };
        overlay.querySelector('#confirmCancel').onmouseover = function() { this.style.borderColor = '#c4bfb8'; };
        overlay.querySelector('#confirmCancel').onmouseout = function() { this.style.borderColor = 'rgba(0,0,0,0.06)'; };
    });
}

// 注入动画样式（只注入一次）
if (!document.getElementById('confirm-style')) {
    const s = document.createElement('style');
    s.id = 'confirm-style';
    s.textContent = '@keyframes fadeIn{from{opacity:0}to{opacity:1}}@keyframes slideUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}';
    document.head.appendChild(s);
}
