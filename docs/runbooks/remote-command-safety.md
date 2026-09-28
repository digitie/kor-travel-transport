# 원격 명령 안전 수칙

이 문서는 `kor-travel-transport`를 Windows PowerShell에서 SSH로 원격 작업할 때 반복되었던 인용부호, 인코딩, 변수 충돌 실수를 줄이기 위한 재발 방지 메모다.

## 왜 필요한가

ODROID M1S 유지보수 중 아래와 같은 실수가 반복된 적이 있다.

- PowerShell 문자열 안에 SSH 원격 명령을 넣고, 그 안에 다시 `bash -lc`, `python -c`, SQL 문자열, JSON 문자열을 겹쳐 넣다가 인용부호가 깨짐
- PowerShell 예약 변수인 `$Host`를 일반 변수처럼 사용하다가 충돌
- Windows에서 만든 스크립트를 BOM 포함 UTF-8로 저장해서 shebang이 깨짐
- `sudo` 비밀번호 전달 방식이 맞지 않아 `Sorry, try again.`가 반복됨
- 삭제 작업 전에 대상 건수 확인이나 백업 없이 바로 원격 DB를 건드리려다 작업 난도가 올라감

## 기본 원칙

1. 복잡한 원격 작업은 인라인 원라이너보다 임시 스크립트 업로드 후 실행을 기본으로 삼는다.
2. `python -c` 원라이너 안에 복잡한 문자열 포맷, SQL, JSON을 함께 넣지 않는다.
3. PowerShell 예약 변수와 충돌하는 이름을 쓰지 않는다.
4. 삭제나 수정 작업은 항상 `건수 확인 -> 백업 -> 실행 -> 후속 검증` 순서로 진행한다.
5. 원격 자동화 실패 원인을 문서로 남긴다.

## 권장 패턴

### 1. 긴 원격 명령은 스크립트 파일로 분리

권장:

- 로컬에서 `.sh` 임시 파일 작성
- `pscp`로 원격 `/tmp`에 업로드
- `plink`로 실행
- 실행 후 임시 파일 삭제

비권장:

- PowerShell 한 줄 안에 `plink "bash -lc 'python -c ...'"` 형태로 모든 로직을 밀어 넣는 것

## 2. 스크립트 인코딩은 UTF-8 BOM 없음

Windows에서 만든 셸 스크립트는 `UTF-8 BOM 없음`으로 저장한다.

이유:

- BOM이 있으면 첫 줄 `#!/usr/bin/env bash`가 깨져 실행 오류가 날 수 있다.

## 3. PowerShell 예약 변수 이름 피하기

사용 금지 예:

- `$Host`
- `$PID`
- `$Error`

권장 예:

- `$remoteHost`
- `$remoteUser`
- `$remotePort`

## 4. sudo 전달은 본 작업 전에 짧게 검증

원격에서 `sudo`가 필요한 경우 본 작업 전에 아래처럼 간단한 검증을 먼저 한다.

예:

```powershell
echo <password> | sudo -S -p '' whoami
```

이 검증이 실패하면 긴 삭제/배포 명령도 실패할 가능성이 높다.

## 5. DB 삭제 작업 표준 절차

원격 SQLite 변경 작업은 아래 순서를 따른다.

1. 기준 시각을 KST와 UTC로 함께 명시
2. 삭제 대상 row 수 조회
3. 같은 볼륨 안에 백업 생성
4. 참조 관계가 있으면 FK 영향 먼저 정리
5. 삭제 실행
6. 삭제 후 남은 row 수와 최소 시각 재확인
7. `health`, 주요 API, 수집기 상태 확인

## 6. SQLite 시각 비교 주의

SQLite의 `DateTime` 컬럼이 문자열로 저장될 때는 `2026-04-27 12:00:00.000000` 같은 형식으로 들어갈 수 있다.

주의:

- 저장값이 공백 구분 형식인데 비교값을 `2026-04-27T12:00:00Z`처럼 ISO 형식으로 넣으면 문자열 비교 결과가 어긋날 수 있다.
- 같은 날짜라도 `' '`와 `'T'`의 정렬 순서 때문에 기대보다 더 많은 row가 삭제될 수 있다.

권장:

- SQLite 직접 정리 작업에서는 `datetime(column) < datetime(?)` 형태로 비교한다.
- 비교 파라미터는 `YYYY-MM-DD HH:MM:SS` 형식으로 맞춘다.
- 삭제 후 `min(observed_at)` 같은 확인 쿼리로 실제 남은 최솟값을 바로 검증한다.

## 7. 권장 체크리스트

- 기준 시각을 절대 시각으로 적었는가
- PowerShell 예약 변수 이름을 피했는가
- 인라인 원라이너 대신 스크립트 업로드 방식으로 바꿀 수 없는가
- 원격 스크립트 인코딩이 BOM 없는 UTF-8인가
- `sudo` 검증을 먼저 했는가
- 삭제 전에 건수와 백업을 확인했는가
- 작업 후 `health`와 핵심 API를 다시 호출했는가

## 관련 문서

- [deployment.md](deployment.md)
- [troubleshooting.md](troubleshooting.md)
- [docs/current-state.md](../current-state.md)
## 8. Docker stdin heredoc

- `docker run ... python - <<'PY'` 또는 `docker exec ... python - <<'PY'` 형태로 표준입력을 넘길 때는 `-i`를 반드시 넣는다.
- `-i`가 없으면 컨테이너가 stdin을 받지 못해서 Python 코드가 비어 있는 것처럼 실행되고, 스크립트가 성공한 것처럼 보여도 실제 작업은 일어나지 않을 수 있다.
