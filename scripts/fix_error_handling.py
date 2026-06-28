import sys, os, re
sys.stdout.reconfigure(encoding='utf-8')

# The fix: in catch blocks, check if the error has a response with detail
# Pattern: catch (e) { showErrorModal('generic') }
# Fix to: catch (e) { showErrorModal(e.message || '网络异常') }

for f in ['config.html', 'index.html', 'logs.html', 'users.html']:
    path = f'app/static/{f}'
    c = open(path, 'r', encoding='utf-8').read()
    changed = False

    # Replace generic catch error messages
    replacements = [
        ("showErrorModal('网络请求失败，请检查网络连接后重试')", "showErrorModal('网络请求失败，请检查网络连接后重试')"),
        ("showErrorModal('操作执行失败，请稍后重试')", "showErrorModal('操作失败，请稍后重试')"),
    ]

    # Also update the loadXxx functions to check response status
    # For users.html, the loadUsers function already has the fix
    # For other pages, we need to add 403 checking

    print(f'{f}: checking patterns...')
