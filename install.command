#!/bin/zsh
set -eu
cd -- "${0:A:h}"
for merge_python in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [[ -x "$merge_python" ]]; then
        exec "$merge_python" build_install.py
    fi
done
print -u2 'Homebrew Python is required. Run: brew install python ffmpeg'
exit 1
