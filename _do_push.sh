#!/bin/bash
cd "/d/PyCharmFiles/Argus" || exit 1

echo "=== Step 1: git add ==="
git add -A
echo "Done."

echo ""
echo "=== Step 2: git status ==="
git status --short
echo ""

echo "=== Step 3: git commit ==="
git commit -m "Initial commit: Argus YOLO Stream Alarm System"
echo ""

echo "=== Step 4: git push ==="
git push master main:master

echo ""
echo "=== ALL DONE ==="
