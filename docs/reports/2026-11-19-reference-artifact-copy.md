# 기준정보 artifact 저장의 native COPY — 2026-11-19

배포 직후 rail 첫 요청은 기존 df878 이미지에서200 7.574초였고, 최초 구성은 source·주소 DTO 검증과 canonical 본문 저장을 함께 수행했다. 로컬 전체 handler에서 저장 구간의 비용을 확인해 asyncpg의 공개 `copy_records_to_table`을 사용한다. 별도 연결·commit·SDK 우회는 추가하지 않는다.

기존 AsyncSession transaction의 공개 raw connection을 사용하며 한 묶음400행·전체16MiB/항목 상한·묶음 전후15초 예산을 유지한다. 검산한 canonical JSON 문자열을 설치된 SQLAlchemy/asyncpg JSONB codec에 전달하므로 다시 loads/dumps하지 않는다. PostgreSQL의 다른 driver와 SQLite는 기존 INSERT 경로를 유지한다. PostgreSQL 원시 오류는 원본 SQLSTATE를 가진 DBAPIError로 전달해 기존40001 한 번 재시도·55P03 즉시503 정책을 지킨다. 실패·취소 뒤 부분 artifact를 commit하지 않는다.

## 검증

- 실제 PostgreSQL의 집중10건(신규9개 계약+기존402행 본문 검사) PASS134.22초. Unicode·NULL·부호 있는0·400+2묶음/ordinal·같은 transaction·두 번째 묶음 오류/취소/중복/수량 불일치 rollback·시간 예산·SQLSTATE 재시도·요청 계측을 확인했다.
- 최종 제품 함수를 실제 import한 전체 handler의1466/4000행 각3교대 쌍에서 전체 페이지/순회/저장 본문·ETag·14개 무결성 조건이 같았다.

| 항목 | 기준 | COPY | 범위 |
| --- | ---: | ---: | --- |
| 1466행 handler 중앙 wall | 570.498ms | 389.773ms | 31.68% 감소 |
| 4000행 handler 중앙 wall | 1216.212ms | 872.192ms | 28.29% 감소 |
| 1466행 process CPU 중앙 | 178.772ms | 182.138ms | 약1.9% 증가 |
| 4000행 process CPU 중앙 | 415.832ms | 370.443ms | 약10.9% 감소 |

동일 고정 합성 시각·ID·입력의 x86_64 직접 handler 비교이며 ASGI·background 작업·Odroid의 실제 첫 요청을 포함하지 않는다. DB와 driver 메모를 강제 cold로 만들지 않았고 양쪽을 같은 횟수 준비했다. RSS는 같은 프로세스의5ms 표본이므로 엄격한 상한/격리 할당량으로 해석하지 않는다. 초기 외부 prototype 수치738→342ms는 별도로 보존하고 위의 최종 제품 함수 결과와 섞지 않는다.

COPY는 SQLAlchemy cursor hook 밖에서 실행돼 benchmark의 hook-only query count 감소는 쿼리 제거의 증거가 아니다. 제품은 요청 ContextVar에 논리 native COPY 시도와 성공 왕복 시간을 더한다. driver 내부 type/prepare 질의는 별도 계수하지 않으며 실제 PostgreSQL 전체 문장 수나 DB CPU라고 표시하지 않는다.

실패·부분 검증은 보존한다. 최초 집중 실행 중 SQLSTATE 전파 수정을 추가해 그 실행은 최종 source 증거로 사용하지 않고 자기 로컬 pytest만 종료했다. 남은 자기 DB의 연결이 자연 종료한 뒤 해당 DB만 정리했다. 최종 집중 실행과 benchmark의 자기 UUID DB도 정리했고 공유 fixture·이미지·캐시는 보존했다.

## 반영 경계

최종 네 제품/시험 파일 SHA에 대한 두 독립 집중 리뷰는 PASS다. 다음은 정확 커밋 CI·정상 캐시 빌드/native 검산·SDK621의 실제 이미지 적용/원상 일정 복원·운영 첫200/조건부304 검증이다. 현재 df878 운영과 기존 source/이미지 영수증은 유지하며 이 로컬 결과를 운영1초 달성이나503 근본 해소로 제시하지 않는다. CI 순서 조정은 마지막 업무로 남긴다.
