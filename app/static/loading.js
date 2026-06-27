/**
 * 全局加载指示器
 * 在页面顶部显示一个细线加载条
 */
function showLoading() {
    let bar = document.getElementById('globalLoadingBar');
    if (!bar) {
        bar = document.createElement('div');
        bar.id = 'globalLoadingBar';
        bar.style.cssText = 'position:fixed;top:0;left:0;width:0;height:2px;background:linear-gradient(90deg,#3b82f6,#8b5cf6);z-index:99999;transition:width 0.3s ease;';
        document.body.appendChild(bar);
    }
    bar.style.width = '30%';
    setTimeout(() => { bar.style.width = '70%'; }, 100);
}

function hideLoading() {
    const bar = document.getElementById('globalLoadingBar');
    if (bar) {
        bar.style.width = '100%';
        setTimeout(() => { bar.style.opacity = '0'; setTimeout(() => bar.remove(), 300); }, 200);
    }
}

// 自动拦截 fetch 显示加载条
const _origFetch = window.fetch;
window.fetch = function(...args) {
    showLoading();
    return _origFetch.apply(this, args).finally(hideLoading);
};
