# CrashLoopBackOff — 설정·환경변수 오류

**확인할 것**
- `kubectl -n <ns> logs <pod> --previous`로 직전 컨테이너의 마지막 로그를 본다. "required", "not set", "missing", "invalid config" 같은 문구가 있는지 본다.
- `lastState.terminated.reason`이 `Error`이고 종료 코드가 1 같은 애플리케이션 종료 코드인지 본다(OOMKilled·137이면 메모리 런북).
- 최근에 바뀐 ConfigMap·Secret 참조·환경변수가 있는지 Deployment의 `env`, `envFrom`을 본다.

**조치 (사람이 결정)**
1. 빠진 설정 값을 채우거나 잘못된 값을 고친 뒤 다시 배포한다.
2. 원인이 최근 배포라면 이전 리비전으로 되돌린다 (`kubectl rollout undo`는 사람이 실행).
