# ADR-008: 통합 교통정보 저장소를 `kor-travel-transport`로 개명한다

## 상태

accepted

## 맥락

저장소의 실제 목표가 공항 주차 웹앱을 넘어 국내 여행에 필요한 공항·열차·고속도로·
도시철도·여객항구·배편 데이터를 주기적으로 수집하고 PostgreSQL과 OpenAPI로 제공하는
통합 교통정보 라이브러리/API로 확장됐다. 기존 `kor-travel-airport` 이름은 현재 범위를
오해하게 한다. 사용자는 GitHub 프로젝트를 `kor-travel-transport`로 바꾸고 기존
`kor-travel-airpot`(오타 포함) 항목을 정리하도록 요청했다.

## 결정

- GitHub canonical repository와 현재 작업 브랜치의 식별자를
  `digitie/kor-travel-transport`로 변경한다.
- GitHub Projects에서 이전 이름으로 남은 항목은 목록을 확인한 뒤 삭제한다. 저장소
  코드·커밋·PR 기록은 삭제하지 않는다.
- Python backend/frontend package metadata와 현재 목적 문서를 `kor-travel-transport`로
  갱신한다. 화면 브랜드 `parking-radar`, 백업 파일 접두어, 기존 사용자 API 계약은
  호환성을 위해 유지한다.
- 운영 중인 n150의 Compose project, 외부 Docker network, named volume, 앱 디렉터리는
  이 PR에서 자동 삭제하거나 재생성하지 않는다. 해당 리소스 이름 변경은 데이터 백업과
  별도 cutover가 필요한 운영 작업이므로, 현재 배포가 끊기지 않도록 legacy 이름을
  호환 레이어로 문서화한다.

## 결과

- 새 기능이 교통정보 범위를 명확히 표현하고 provider·DB·API 계층의 책임을 설명한다.
- 운영 리소스 이름을 보존하므로 저장소 개명만으로 PostgreSQL volume이나 네트워크를
  잃지 않는다.
- 향후 운영 리소스 개명 시에는 `pg_dump`, 새 네트워크 연결, rollback 검증을 포함한
  별도 migration task가 필요하다.
