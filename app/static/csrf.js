/**
 * CSRF token helper — reads cookie and sends as header.
 */
function getCsrfToken() {
    const match = document.cookie.match(/csrf_token=([^;]+)/);
    return match ? match[1] : '';
}

function csrfFetch(url, opts = {}) {
    const t = localStorage.getItem('token');
    if (!opts.headers) opts.headers = {};
    if (t) opts.headers['Authorization'] = 'Bearer ' + t;
    // Add CSRF token for state-changing requests
    const method = (opts.method || 'GET').toUpperCase();
    if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
        opts.headers['X-CSRF-Token'] = getCsrfToken();
    }
    return fetch(url, opts);
}
