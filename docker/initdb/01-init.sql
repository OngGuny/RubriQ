-- 앵커 에세이 임베딩용 확장
CREATE EXTENSION IF NOT EXISTS vector;
-- Langfuse는 자체 DB를 사용한다 (앵커 데이터와 분리)
CREATE DATABASE langfuse;
