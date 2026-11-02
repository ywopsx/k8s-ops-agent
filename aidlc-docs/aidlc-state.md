# AI-DLC 진행 상태

## 프로젝트 정보

- **프로젝트**: k8s-ops-agent (EKS 클러스터 운영 에이전트)
- **유형**: Brownfield (Unit 1 `preflight/` v0.1 구현 완료)
- **시작일**: 2026-11-02

## 작업 단위

| 단위 | 내용 | 상태 |
| --- | --- | --- |
| Unit 1 | 노드 교체 사전 점검 (`preflight/`, `rehearsal/`, `agent/`) | v0.1 구현 완료, 백로그 진행 중 (우선) |
| Unit 2 | 알림 1차 분석 → Slack 스레드 | 요구사항 질문지 답변 대기 (사용자가 직접 작성) |

## 단계 진행

### INCEPTION

- [x] Workspace Detection — 기존 코드(Unit 1), README, CLAUDE.md 확인
- [x] Reverse Engineering — 생략. Unit 1은 README·CLAUDE.md·00-context.md로 충분하다고 판단 (2026-11-02)
- [ ] Requirements Analysis — **진행 중**: Unit 2 질문지 답변 대기
- [ ] User Stories
- [ ] Workflow Planning
- [ ] Application Design
- [ ] Units Generation

### CONSTRUCTION

- [ ] Functional Design
- [ ] NFR Requirements / Design
- [ ] Code Generation
- [ ] Build and Test

## 현재 할 일

1. [x] Unit 1 백로그 1번(lb-target-instance, topology-spread) 구현 완료, kind 데모 확인 완료, `docs/AI_USAGE.md` 기록 완료 (사용자)
2. [x] Unit 1 백로그 2번(drain 검증) 구현 완료, 단위 테스트 55개 통과, kind 데모 확인 완료 (2026-11-03, 사용자)
   - 리포트: `out/rehearsal/20261103-000339/` (git에는 넣지 않음)
   - 결과: PDB에 막힘 1 · 재배치 실패 2 · 컨트롤러 없음 1 · evict 실패 0 · 재배치 완료 2 · 건너뜀 2, 전체 61.8초(타임아웃 60초), uncordon 함
   - 예측 비교: 예측한 6건(발생 5, 발생 안 함 1) 모두 README 기대 결과와 일치. 예측 못 한 다운타임 1건(`order-api`)
3. [x] Unit 1 백로그 7번(colocated-replicas) 결정(추천안 + ③ 보완), 구현 완료, 단위 테스트 75개 통과, kind 데모 두 개 확인 완료 (2026-11-03, Claude 실행)
   - `run-demo.sh`: HIGH 3 · MEDIUM 9, README 기대 결과 표와 일치. `order-api`·`zone-spread`가 colocated-replicas MEDIUM
   - `run-drain-demo.sh` (`out/rehearsal/20261103-015605/`): 예측 비교 7행 모두 예측된 문제(예측함·발생 6, 예측함·발생 안 함 1), 예측 못 함·발생 0
   - 데모 스크립트 수정: 새 네임스페이스의 default ServiceAccount가 생기기 전에 단독 Pod를 만들어 거부되던 문제
4. (사용자) `inception/requirements/requirement-verification-questions.md`의 `[Answer]:` 칸을 채운다.
