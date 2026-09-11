# 004. Langfuse를 v4로 올리고 SDK를 맞춘다

- 상태: 채택
- 날짜: 2026-09-11

## 맥락

Langfuse 서버를 v2로 띄워뒀는데(컨테이너 2개, compose 한 파일),
Python SDK가 4.15.1이었다. 붙이려 하니 통신이 되지 않았다.

```
auth_check: ValidationError — Projects.data.0.organization Field required
```

SDK v3부터 OpenTelemetry 기반으로 재작성되면서 API 응답 스키마가 바뀌었다.
v2 서버의 `/api/public/projects`에는 `organization`·`metadata` 필드가 없다.
`start_as_current_span` 같은 메서드도 존재하지 않는다.

## 선택지

- **A) SDK를 v2로 고정** (`langfuse>=2.60,<3`) — 서버 v2 유지, compose 한 파일 그대로.
  격리 환경에서 실제로 동작을 확인했고 트레이스가 서버에 들어가는 것까지 봤다.
  대가는 레거시 SDK를 쓰는 것.
- **B) 서버를 v4로 올림** — Langfuse v4는 OLTP(postgres) 외에
  OLAP(ClickHouse) · 큐(Redis) · 블롭(MinIO)을 요구한다. 컨테이너 2개 → 6개.
  ClickHouse가 메모리를 꾸준히 쓴다. 대신 최신 스택이고 SDK를 고정하지 않아도 된다.
- C) 관측 추상화만 만들고 Langfuse 연결은 보류.

## 결정

**B.** 서버를 `langfuse:4`로 올리고 SDK를 `>=4.15,<5`로 맞췄다.

## 트레이드오프

- **로컬 자원 사용이 크게 늘었다.** 컨테이너 6개, ClickHouse 포함.
  개인 노트북에서 다른 작업과 병행하기 부담스러울 수 있다.
- **compose가 복잡해졌다.** "한 파일"은 유지했지만 서비스 6개와
  S3·Redis·ClickHouse 환경변수가 들어갔다. 공식 compose에서
  이 프로젝트에 필요 없는 것(SMTP, AWS, in-app agent, MCP)은 걷어냈다.
- **v4는 events_only 모드**라 레거시 `/api/public/traces` 엔드포인트가 없다.
  트레이스 확인은 UI나 ClickHouse 직접 조회로 한다. 스크립트로 검증할 때 이게 걸린다.

## 덧붙인 결정

**헤드리스 초기화를 쓴다.** `LANGFUSE_INIT_*` 환경변수로 조직·프로젝트·API 키를
컨테이너 기동 시 결정적으로 생성한다. UI에서 수동 가입하는 방식은 재현되지 않는다.

**ClickHouse와 Redis는 호스트에 노출하지 않는다.** Langfuse 컨테이너만 쓰고,
9000번은 다른 프로세스와 자주 부딪힌다(실제로 기동 중 충돌했다).
조회는 `docker exec`로 한다.

## 되돌리는 조건

로컬 자원 부담으로 개발이 느려지면 A로 되돌린다.
그 경우 SDK를 v2로 내리고 `observability/langfuse.py`의
`start_as_current_observation` 호출부를 v2 API(`trace()` / `generation()`)로 바꾼다.
파사드(`LangfuseTracer`)가 SDK를 감싸고 있어 교체 범위는 그 파일 하나다.
