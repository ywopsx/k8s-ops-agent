# 컨테이너 OOMKilled

**확인할 것**
- `kubectl -n <ns> get pod <pod> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}'` 결과가 `OOMKilled`인지 본다. 종료 코드는 보통 137이다.
- Pod의 `resources.limits.memory`와 재시작 횟수, 재시작이 일정한 작업(배치, 대용량 요청) 뒤에 생기는지 본다.
- 로그가 아무 오류 없이 끊겼다면 애플리케이션 오류보다 커널의 OOM 종료일 가능성이 높다.

**조치 (사람이 결정)**
1. 실제 사용량을 확인한다 (`kubectl top pod`, 모니터링 지표). 
2. 정상 사용량이 limit을 넘는다면 limit·request를 올린다. 누수라면 이전 버전으로 되돌리고 원인을 찾는다.
3. JVM·Node.js 등은 힙 설정이 컨테이너 limit보다 크지 않은지 확인한다.
