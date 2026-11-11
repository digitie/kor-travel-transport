# Transport C11 최초 릴리스 소비 검증 — 2026-11-12

부모로부터 b327e2a의 C11 미커밋 변경과 실제 설치를 인수했다.
공통 PR49 main e8ed3ae75000be5cd22a3a11492bd97660635d78에 병합된 최초 릴리스의
UI0.2.0/tokens0.1.1 동일 bytes를 사용한다. pack source는 a35481349d6747b4f13b958ae64d9c0bbd0b5413이다.
동일 버전의 재pack·산출물 수정은 하지 않았다. 원장은 당시 metadata를 포함해 그대로 보존했다.

## 이번 delta

공개/관리자 manifest·lock·vendor·원장을 C11에 정렬했다.
공식 이름 @radix-ui/react-focus-scope@1.3.1+kortravel.fix.2를 직접 runtime file로 설치하고
각 앱 루트 override를 $@radix-ui/react-focus-scope로 고정한다.
이 엔진은 부모가 동결한 source1752a539/33511bytes/SHA256
1ca04870692565c243130d99c3dba91f3ac853ab2ec9538fc7b658b17fb7b49a와 같다.
미사용 fix1 vendor 두 개는 참조 부재를 확인한 뒤 제거했다.
중앙 workflow code/common-ref는 exact55a921b55d248106cbe320e7f5305f3d3cdb60fe다.
앱·API·인증·세션·데이터베이스 소스 변경은 없다.

## 확인한 gate와 남은 gate

부모의 실제 C11 전체 결과는 공개164/관리자356 unit PASS, 양쪽 타입/lint PASS,
Doctor 오류0/경고0이다. 원문과 SHA256은 [검증 JSON](2026-11-12-transport-c11-validation.json)에 기록했다.
초기 installed guard는 harness가 중앙 전용 KT_REQUIRE_CANONICAL을 잘못 전달해 거부됐다.
명시 policy/canonical의 외부 검사는 통과했고, 최종 standalone 호출도 guard-final.json에서 exit0이다.
실패 기록은 삭제하지 않았다.

인수 후 tgz·원장·lock·모든 도달 설치 사본을 직접 대조했다.
공개153파일, 관리자263파일 모두 exact이며 installed/external canonical guard도 다시 PASS다.
기존 node_modules/.next symlink 대상은 보존했고 install/build를 WSL root에서 실행하지 않았다.

새 엔진의 runtime이 바뀌었으므로 새 N150 native/Alpine production build와
각 경로의 공개4/관리자18 Chromium gate는 슬롯 배정 후 실행한다. 현재 PENDING이며
옛 c8 브라우저 통과를 새 C11 통과로 보고하지 않는다.
현재 커밋의 PR181 CI와 독립 리뷰 delta 확인도 남아 있다.

backend 소스가 같으므로 기존 WSL1511PASS/39SKIP·Docker1508PASS/42SKIP를 보존한다.
metadata 갱신만을 이유로 전체 backend를 다시 실행하지 않았다.
이전 오류·중단·c9/c8 증거는 [기존 검증 기록](2026-11-11-common-ui-validation.md)과
로컬 validation에 남겼다.

## 배포 준비

두 독립 리뷰·정확 HEAD CI·새 엔진 브라우저·PRmerge 뒤 부모 go를 받아
exact merge SHA의 새 public/admin 이미지를 공식 staging/entry로 배포한다.
저장소 루트 build context, NVMe, Manager 대상/instance 정본, Transport만의
instigator 중지·run/worker drain·원 상태 복구와 secret 보존을 따른다.
구체 태그·명령·health/로그인/대표화면 smoke와 실패 복구 경계는 기존 검증 기록의
배포 계획 및 최신 배포 런북·ADR014를 따른다. DB/RustFS lifecycle은 변경하지 않는다.
현재 merge SHA는 미정이며 운영 배포는 실행하지 않았다.
