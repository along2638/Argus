#!/bin/bash
cd /d/PyCharmFiles/Argus

echo "=== Staging files ==="
${0%/*}/../mingw64/bin/git add -A

echo ""
echo "=== Current status ==="
${0%/*}/../mingw64/bin/git status --short

echo ""
echo "=== Committing ==="
${0%/*}/../mingw64/bin/git commit -m "Initial commit: Argus YOLO Stream Alarm System"

echo ""
echo "=== Pushing to GitHub ==="
${0%/*}/../mingw64/bin/git push origin master

echo ""
echo "=== Done ==="
