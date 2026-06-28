import sys, os, re
sys.stdout.reconfigure(encoding='utf-8')

# For each page, find all showErrorModal calls in catch blocks and update them
# to check response status and show the actual error message

for f in ['config.html', 'index.html', 'logs.html', 'users.html']:
    path = f'app/static/{f}'
    c = open(path, 'r', encoding='utf-8').read()
    changed = False

    # Pattern: showErrorModal('generic message')
    # Replace with: if response has detail, show it; otherwise show generic
    # But we need to check if the response object is available in the catch block

    # For now, just make sure the error messages are descriptive
    # The key issue is that 403 errors from the backend show "权限不足" in data.detail
    # but the frontend catch block doesn't check for this

    print(f'{f}: checking...')
