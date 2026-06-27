/**
 * 暗色模式切换
 */
function initTheme() {
    const saved = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', saved);
    updateThemeButton(saved);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateThemeButton(next);
}

function updateThemeButton(theme) {
    const btn = document.getElementById('themeToggle');
    if (btn) btn.textContent = theme === 'dark' ? '浅色' : '深色';
}

// 注入暗色模式 CSS
const darkCSS = `
[data-theme="dark"] {
    --bg: #0f172a;
    --bg-card: rgba(30,41,59,0.8);
    --bg-card-solid: #1e293b;
    --bg-input: rgba(255,255,255,0.05);
    --border: rgba(255,255,255,0.08);
    --border-focus: rgba(255,255,255,0.2);
    --ink: #e2e8f0;
    --ink-light: #cbd5e1;
    --ink-muted: #94a3b8;
    --ink-faint: #475569;
    --accent: #e2e8f0;
    --accent-soft: rgba(255,255,255,0.06);
    --success: #4ade80;
    --success-bg: rgba(74,222,128,0.1);
    --danger: #f87171;
    --danger-bg: rgba(248,113,113,0.1);
    --warning: #fbbf24;
    --warning-bg: rgba(251,191,36,0.1);
    --shadow: 0 1px 3px rgba(0,0,0,0.2), 0 8px 32px rgba(0,0,0,0.3);
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.2);
}
[data-theme="dark"] body::before {
    background: radial-gradient(ellipse 80% 50% at 20% 30%,rgba(59,130,246,0.05) 0%,transparent 70%),
                radial-gradient(ellipse 60% 40% at 75% 60%,rgba(99,102,241,0.04) 0%,transparent 60%);
}
[data-theme="dark"] .header { background: rgba(30,41,59,0.9); }
[data-theme="dark"] .card { background: rgba(30,41,59,0.8); }
[data-theme="dark"] .form-input, [data-theme="dark"] .form-select { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.08); color: #e2e8f0; }
[data-theme="dark"] .form-input::placeholder { color: #475569; }
[data-theme="dark"] .custom-select-trigger { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.08); color: #e2e8f0; }
[data-theme="dark"] .custom-select-options { background: #1e293b; border-color: rgba(255,255,255,0.08); }
[data-theme="dark"] .custom-option:hover { background: rgba(255,255,255,0.06); }
[data-theme="dark"] .custom-option.selected { background: rgba(255,255,255,0.06); }
[data-theme="dark"] .stat-card { background: rgba(255,255,255,0.03); }
[data-theme="dark"] .upload-zone { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.1); }
[data-theme="dark"] .upload-zone:hover { background: rgba(255,255,255,0.05); }
[data-theme="dark"] .image-area { background: rgba(255,255,255,0.02); }
[data-theme="dark"] .history-thumb { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.08); }
[data-theme="dark"] .result-panel { border-color: rgba(255,255,255,0.08); }
[data-theme="dark"] .detection-item { border-color: rgba(255,255,255,0.05); }
[data-theme="dark"] .detection-bar { background: rgba(255,255,255,0.05); }
[data-theme="dark"] .user-table th { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.05); }
[data-theme="dark"] .user-table td { border-color: rgba(255,255,255,0.05); }
[data-theme="dark"] .user-table tr:hover td { background: rgba(255,255,255,0.02); }
[data-theme="dark"] .log-table th { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.05); }
[data-theme="dark"] .log-table td { border-color: rgba(255,255,255,0.05); }
[data-theme="dark"] .config-input { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.08); color: #e2e8f0; }
[data-theme="dark"] .canvas-wrapper { background: rgba(255,255,255,0.02); }
[data-theme="dark"] .canvas-box { background: #1e293b; border-color: rgba(255,255,255,0.08); }
[data-theme="dark"] .sidebar { background: rgba(30,41,59,0.8); border-color: rgba(255,255,255,0.08); }
[data-theme="dark"] .alarm-item:hover { background: rgba(255,255,255,0.02); }
[data-theme="dark"] .stream-item:hover { background: rgba(255,255,255,0.04); }
[data-theme="dark"] .modal { background: #1e293b; }
[data-theme="dark"] .bar { background: #64748b !important; opacity: 0.85; }
[data-theme="dark"] .bar:hover { opacity: 1; background: #94a3b8 !important; }
[data-theme="dark"] .bar-value { color: var(--ink-light); }
[data-theme="dark"] .legend-dot { opacity: 0.9; }
[data-theme="dark"] .chart-head { border-color: rgba(255,255,255,0.06); }
[data-theme="dark"] .stat-card { border-color: rgba(255,255,255,0.06); }
[data-theme="dark"] .chart-box { border-color: rgba(255,255,255,0.06); }
[data-theme="dark"] .empty { color: #475569; }
[data-theme="dark"] .footer { color: #475569; }
`;

const style = document.createElement('style');
style.textContent = darkCSS;
document.head.appendChild(style);

initTheme();
