#!/bin/sh
set -e
REAL="/root/成都修茈科技有限公司"
test -d "$REAL" || { echo "not a directory: $REAL" 1>&2; exit 1; }
ln -snf "$REAL" /root/modstore-git
printf '%s' "[ok] /root/modstore-git -> "
readlink -f /root/modstore-git
printf '\n'
