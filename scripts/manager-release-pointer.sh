# shellcheck shell=bash
# Manager current release 표식(kor-travel-docker-manager ADR-60, docs/service-current-release.md).
# 배포 스크립트가 source한다. 표식은 root CLI만 쓴다 — 이 저장소는 파일을 직접 만들지 않는다.
#  - 교체 전: 실행 중 이미지가 current와 같아야 한다(drift·표식 없음·CLI 없음이면 멈춘다).
#  - health 뒤: 실제 실행 이미지를 새 current로 발행한다(adopt --replace-current).
# .release-sha/.staged-release-sha/.transport-admin-release-sha는 준비·소스 표식으로 그대로 둔다(ADR-60 D6).

release_pointer_cli() {
  sudo -n ktdctl service-release "$@"
}

require_release_pointer_in_sync() {
  local status=0 report
  report="$(release_pointer_cli verify transport --json 2>&1)" || status=$?
  [[ "${status}" == 0 ]] && return 0
  printf '%s\n' "${report}" >&2
  case "${status}" in
    1) echo "Refusing production deployment: running transport images drift from the Manager current release. Find who changed them; if the running set is the verified one, register it first: sudo ktdctl service-release adopt transport --confirm --replace-current --oneshot-image migrate=sha256:<id>." >&2 ;;
    *) echo "Refusing production deployment: cannot verify the Manager current release of transport (Manager without service-release, missing or invalid pointer)." >&2 ;;
  esac
  return 2
}

# 현재 표식이 기록한 migrate 이미지 ID. migrate를 바꾸지 않는 배포(admin)가 그대로 넘긴다.
current_migrate_image_id() {
  release_pointer_cli show transport --json |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["groups"]["core"]["oneshot_images"]["migrate"])'
}

# $1: 이번 release의 migrate 이미지 ID(sha256:<64hex>).
publish_release_pointer() {
  local migrate_id="$1"
  if [[ ! "${migrate_id}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "Release pointer not published: invalid migrate image ID ${migrate_id@Q}." >&2
    return 2
  fi
  if ! release_pointer_cli adopt transport --confirm --replace-current --oneshot-image "migrate=${migrate_id}" >/dev/null; then
    echo "Deployment is healthy but the Manager current release was NOT published. Run: sudo ktdctl service-release adopt transport --confirm --replace-current --oneshot-image migrate=${migrate_id}" >&2
    return 2
  fi
  echo "Manager current release of transport published (migrate=${migrate_id})."
}
