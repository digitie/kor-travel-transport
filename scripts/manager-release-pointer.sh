# shellcheck shell=bash
# Manager current release 표식(kor-travel-docker-manager ADR-60, docs/service-current-release.md).
# 배포 스크립트가 source한다. 표식은 root CLI만 쓴다 — 이 저장소는 파일을 직접 만들지 않는다.
#  - 교체 전: 실행 중 이미지가 current와 같아야 한다(drift·표식 없음·CLI 없음이면 멈춘다).
#  - health 뒤: 실제 실행 이미지를 새 current로 발행한다(adopt --replace-current).
# .release-sha/.staged-release-sha/.transport-admin-release-sha는 준비·소스 표식으로 그대로 둔다(ADR-60 D6).

# health는 통과했지만 표식 발행만 실패한 종료 코드. 외부 controller는 이 값을 배포 실패로 복구하지 않는다.
RELEASE_POINTER_UNPUBLISHED_EXIT=3

release_pointer_cli() {
  sudo -n ktdctl service-release "$@"
}

# ALLOW_RELEASE_POINTER_DRIFT=forward-fix: 직전 배포가 검증 뒤 실패해(migration 적용 등) 발행되지 않은
# 이미지가 돌고 있을 때, 그 상태를 고치는 forward-fix 배포만 drift(exit 1)를 넘긴다. 표식 없음·CLI 없음은 넘기지 않는다.
require_release_pointer_in_sync() {
  local status=0 report
  if ! sudo -n true 2>/dev/null; then
    echo "Refusing production deployment: passwordless sudo is required to read the Manager current release." >&2
    return 2
  fi
  report="$(release_pointer_cli verify transport --json 2>&1)" || status=$?
  [[ "${status}" == 0 ]] && return 0
  printf '%s\n' "${report}" >&2
  if [[ "${status}" == 1 ]]; then
    if [[ "${ALLOW_RELEASE_POINTER_DRIFT:-}" == "forward-fix" ]]; then
      echo "WARNING: running transport images drift from the Manager current release; continuing as an explicit forward-fix (ALLOW_RELEASE_POINTER_DRIFT=forward-fix)." >&2
      return 0
    fi
    echo "Refusing production deployment: running transport images drift from the Manager current release. If the running set is the verified one, register it: sudo ktdctl service-release adopt transport --confirm --replace-current --oneshot-image migrate=sha256:<id>. To deploy a forward-fix over an unpublished failed release, set ALLOW_RELEASE_POINTER_DRIFT=forward-fix." >&2
  else
    echo "Refusing production deployment: cannot verify the Manager current release of transport (Manager without service-release, missing or invalid pointer)." >&2
  fi
  return 2
}

# 현재 표식이 기록한 migrate 이미지 ID. migrate를 바꾸지 않는 배포(admin)가 그대로 넘긴다.
current_migrate_image_id() {
  release_pointer_cli show transport --json |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["groups"]["core"]["oneshot_images"]["migrate"])'
}

# $1: 이번 release의 migrate 이미지 ID(sha256:<64hex>).
# 방금 재생성한 컨테이너의 Docker health가 아직 starting일 수 있으므로 adopt(전 역할 healthy 요구)를 제한 횟수만큼 재시도한다.
publish_release_pointer() {
  local migrate_id="$1" attempt attempts="${RELEASE_POINTER_PUBLISH_ATTEMPTS:-16}" delay="${RELEASE_POINTER_PUBLISH_DELAY:-15}"
  if [[ ! "${migrate_id}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "Deployment is healthy but the Manager current release was NOT published: invalid migrate image ID ${migrate_id@Q}." >&2
    return "${RELEASE_POINTER_UNPUBLISHED_EXIT}"
  fi
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if release_pointer_cli adopt transport --confirm --replace-current --oneshot-image "migrate=${migrate_id}" >/dev/null; then
      echo "Manager current release of transport published (migrate=${migrate_id})."
      return 0
    fi
    ((attempt < attempts)) && sleep "${delay}"
  done
  echo "Deployment is healthy but the Manager current release was NOT published. Run: sudo ktdctl service-release adopt transport --confirm --replace-current --oneshot-image migrate=${migrate_id}" >&2
  return "${RELEASE_POINTER_UNPUBLISHED_EXIT}"
}

# migrate를 바꾸지 않는 배포용: 현재 표식의 migrate ID로 발행한다. show 실패도 미발행으로 보고한다.
publish_release_pointer_keeping_migrate() {
  local migrate_id
  if ! migrate_id="$(current_migrate_image_id)"; then
    echo "Deployment is healthy but the Manager current release was NOT published: cannot read the current migrate image ID." >&2
    return "${RELEASE_POINTER_UNPUBLISHED_EXIT}"
  fi
  publish_release_pointer "${migrate_id}"
}
