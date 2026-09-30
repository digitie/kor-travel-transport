#!/usr/bin/env bash
set -euo pipefail

# deploy-server14.sh가 완전한 동기화 뒤에만 발행하는 별도 receipt를 검사한다.
# .release-sha는 현재/이전 배포 식별자이므로 stage 완료의 증거로 쓸 수 없다.
if [[ "$#" != 2 || ! "$2" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Refusing n150 deployment: stage verification needs a directory and full SHA." >&2
  exit 2
fi
marker="$1/.staged-release-sha"
if [[ ! -f "${marker}" || -L "${marker}" ]] \
  || [[ "$(tr -d '\r\n' < "${marker}")" != "$2" ]]; then
  echo "Refusing n150 deployment: candidate sync is incomplete or superseded." >&2
  exit 2
fi
