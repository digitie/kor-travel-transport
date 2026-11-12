# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Youn-sok Choi (digitie)
# 빌드·검사 진입점이다. 운영 배포·마이그레이션·수집을 자동 실행하지 않는다.
.PHONY: frontend-install frontend-check admin-install admin-check backend-install backend-check image-build

frontend-install:
	cd frontend && npm ci --engine-strict

frontend-check:
	cd frontend && npm run check:dependencies
	cd frontend && npm run doctor
	cd frontend && npm test
	cd frontend && npm run type-check
	cd frontend && npm run lint
	cd frontend && npm run build

admin-install:
	cd packages/kor-travel-transport-admin/frontend && npm ci --engine-strict

admin-check:
	cd packages/kor-travel-transport-admin/frontend && npm run check:dependencies
	cd packages/kor-travel-transport-admin/frontend && npm run doctor
	cd packages/kor-travel-transport-admin/frontend && npm test
	cd packages/kor-travel-transport-admin/frontend && npm run type-check
	cd packages/kor-travel-transport-admin/frontend && npm run lint
	cd packages/kor-travel-transport-admin/frontend && npm run build

backend-install:
	cd backend && uv sync --extra dev --locked

backend-check:
	cd backend && uv run --locked python ../scripts/export_openapi.py --check
	cd backend && uv run --locked pytest tests -q

# 값은 BUILD_OPTIONS에 넣지 않고 --public-inputs 파일/stdin으로만 전달한다.
image-build:
	@python3 scripts/build-images.py $(BUILD_OPTIONS)
