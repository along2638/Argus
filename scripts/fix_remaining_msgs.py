import sys, os
sys.stdout.reconfigure(encoding='utf-8')

for f in ['users.html', 'logs.html']:
    path = f'app/static/{f}'
    c = open(path, 'r', encoding='utf-8').read()
    changed = False

    # Replace generic error messages with data.detail
    c = c.replace("showErrorModal(data.detail || '操作失败')", "showErrorModal(data.detail || '操作失败，请稍后重试')")
    c = c.replace("showErrorModal('操作失败，请稍后重试')", "showErrorModal('操作失败，请稍后重试')")

    open(path, 'w', encoding='utf-8').write(c)
    print(f'{f}: updated')
