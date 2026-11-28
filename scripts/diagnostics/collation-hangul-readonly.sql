-- 운영 한글 collation 진단(읽기 전용, docs/audits/2026-11-28-hangul-collation.md). transport DB에서:
--   psql -X -v ON_ERROR_STOP=1 -f prod-collation-diagnose.sql
-- 쓰기·DDL 없음. 표 전체 스캔은 fuel_stations(약 1.2만 행)·fuel_region_summaries 정도만.
\pset pager off
BEGIN READ ONLY;
SET LOCAL statement_timeout = '60s';

\echo '== 1. 서버·DB 정렬 규칙'
SELECT version();
SELECT datname, datcollate, datctype, datlocprovider, datcollversion,
       pg_database_collation_actual_version(oid) AS actual_collversion
  FROM pg_database WHERE datname = current_database();

\echo '== 2. 후보 컬럼: 현재 collation·한글 포함 여부·표/색인 크기(컬럼 collation 변경 시 색인 재생성 비용)'
WITH cand(tbl, col) AS (VALUES
  ('fuel_statistics_daily','scope_key'), ('fuel_statistics_history','scope_key'),
  ('fuel_region_summaries','region_key'), ('fuel_stations','sido_value'), ('fuel_stations','sigungu_value'),
  ('fuel_stations','dong_value'), ('fuel_stations','identity_key'), ('rest_area_references','identity_key'),
  ('rail_station_references','identity_key'), ('highway_traffic_current','identity_key'),
  ('highway_incident_snapshots','identity_key'))
SELECT c.tbl, c.col, coalesce(a.attcollation::regcollation::text, '-') AS collation,
       pg_size_pretty(pg_table_size(format('%I', c.tbl)::regclass)) AS table_size,
       pg_size_pretty(pg_indexes_size(format('%I', c.tbl)::regclass)) AS all_index_size,
       (SELECT string_agg(i.indexrelid::regclass::text || '(' || pg_size_pretty(pg_relation_size(i.indexrelid)) || ')', ', ')
          FROM pg_index i WHERE i.indrelid = format('%I', c.tbl)::regclass AND a.attnum = ANY(i.indkey)) AS indexes_on_column,
       (SELECT reltuples::bigint FROM pg_class WHERE oid = format('%I', c.tbl)::regclass) AS est_rows
  FROM cand c JOIN pg_attribute a ON a.attrelid = format('%I', c.tbl)::regclass AND a.attname = c.col
 ORDER BY 1, 2;

\echo '== 3. 한글(비 ASCII) 비율 — 표본 2000행'
SELECT 'fuel_stations.sido_value' col, count(*) FILTER (WHERE sido_value ~ '[^[:ascii:]]') nonascii, count(*) n FROM (SELECT sido_value FROM fuel_stations LIMIT 2000) s
UNION ALL SELECT 'fuel_stations.identity_key', count(*) FILTER (WHERE identity_key ~ '[^[:ascii:]]'), count(*) FROM (SELECT identity_key FROM fuel_stations LIMIT 2000) s
UNION ALL SELECT 'fuel_region_summaries.region_key', count(*) FILTER (WHERE region_key ~ '[^[:ascii:]]'), count(*) FROM (SELECT region_key FROM fuel_region_summaries LIMIT 2000) s
UNION ALL SELECT 'rest_area_references.identity_key', count(*) FILTER (WHERE identity_key ~ '[^[:ascii:]]'), count(*) FROM (SELECT identity_key FROM rest_area_references LIMIT 2000) s
UNION ALL SELECT 'rail_station_references.identity_key', count(*) FILTER (WHERE identity_key ~ '[^[:ascii:]]'), count(*) FROM (SELECT identity_key FROM rail_station_references LIMIT 2000) s
UNION ALL SELECT 'highway_traffic_current.identity_key', count(*) FILTER (WHERE identity_key ~ '[^[:ascii:]]'), count(*) FROM (SELECT identity_key FROM highway_traffic_current LIMIT 2000) s;

\echo '== 4. 운영 호스트 배율: 시군구 한글 키(약 230개)를 20벌 복제한 약 4,600행 한 번 정렬 — 기본 / C / ICU'
SELECT count(DISTINCT scope_key) AS keys FROM fuel_statistics_daily WHERE scope = 'sigungu';
\timing on
SELECT count(*) FROM (SELECT k.key FROM (SELECT DISTINCT scope_key COLLATE "C" AS key FROM fuel_statistics_daily WHERE scope = 'sigungu') k, generate_series(1,20) ORDER BY k.key COLLATE "default") s;
SELECT count(*) FROM (SELECT k.key FROM (SELECT DISTINCT scope_key COLLATE "C" AS key FROM fuel_statistics_daily WHERE scope = 'sigungu') k, generate_series(1,20) ORDER BY k.key COLLATE "C") s;
SELECT count(*) FROM (SELECT k.key FROM (SELECT DISTINCT scope_key COLLATE "C" AS key FROM fuel_statistics_daily WHERE scope = 'sigungu') k, generate_series(1,20) ORDER BY k.key COLLATE "und-x-icu") s;
\echo '-- 주유소 시도·시군구 정렬 묶음(해시 금지): 기본 vs C'
SET LOCAL enable_hashagg = off;
SELECT count(*) FROM (SELECT sido_value, sigungu_value, count(*) FROM fuel_stations GROUP BY 1,2) s;
SELECT count(*) FROM (SELECT sido_value COLLATE "C", sigungu_value COLLATE "C", count(*) FROM fuel_stations GROUP BY 1,2) s;
RESET enable_hashagg;
\timing off

\echo '== 5. pg_stat_statements(있으면): 누적 시간 상위 중 정렬·묶음이 있는 transport 문장'
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS has_pss \gset
\if :has_pss
SELECT round(total_exec_time)::bigint AS total_ms, calls, round(mean_exec_time::numeric, 1) AS mean_ms,
       round(max_exec_time::numeric, 1) AS max_ms, left(regexp_replace(query, '\s+', ' ', 'g'), 220) AS query
  FROM pg_stat_statements
 WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
   AND query ~* '(order by|group by|distinct|partition by|min\(|max\()'
 ORDER BY mean_exec_time DESC LIMIT 25;
\else
\echo 'pg_stat_statements 없음 — backend slow_request 로그(route·duration)로 대신 본다.'
\endif
ROLLBACK;
