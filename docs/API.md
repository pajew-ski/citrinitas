# API

One door, HTTP on port 8765. Every request except `GET /health` needs `Authorization: Bearer <token>`; the
token is in `/srv/citrinitas/etc/token` on the node. The API reads and never writes.

| Request | Answer |
|---|---|
| `GET /health` | `{"ok": true, "commit": "<sha>"}` without a token |
| `GET /status` | the state document |
| `POST /query` | rows for a template or for read-only SQL |
| `POST /relatio/check` | the verdict on a draft assessment |

Errors are `{"ok": false, "error": "..."}` with status 400, 401, 404, 413 or 500.

## POST /query

Body: `{"template": "<name>", "params": {...}}` or `{"sql": "SELECT ..."}`, optionally `"asof": "<ISO time>"`.
With `asof`, the view `facta` shows what the lake held at that time.

Answer: `{"ok": true, "columns": [...], "rows": [[...]], "row_count": n, "truncated": false, "elapsed_ms": n,
"commit": "<sha>", "asof": null}`. Timestamps are UTC in ISO format.

Limits: templates 20 seconds and 500 rows; SQL one SELECT, 60 seconds, 5 000 rows, 2 GB of memory, no file
outside the lake.

### Templates

| Name | Parameters | Returns |
|---|---|---|
| `status` | none | the state document |
| `series` | `from`, `to`, `bucket` (hour, day, week, month), `time` (reported, reference), `fons`, `domain`, `classis`, `iso3`, `measure` | sum and count per bucket and class |
| `ranking` | `from`, `to`, `by` (iso3, domain, fons, measure, adm1, h3_5), `limit`, the same filters | top values per key and class |
| `lang_gap` | `from`, `to`, `lang` (default `deu`), `min_docs`, `limit` | countries covered in other languages, with the count in the given one |
| `articles` | `from`, `to`, `theme`, `fips`, `lang`, `source`, `limit` | documents of the GDELT knowledge graph |
| `anomalies` | `day`, `days`, `z`, `min_articles`, `roots` (CAMEO root codes) | countries whose share of reporting stands out against their own baseline |
| `provenance` | `row_id` | run, commit and input files with SHA-256 for a row |
| `coverage` | none | the latest coverage matrix |
| `indicators` | none | the latest value of every indicator |
| `probe` | none | the latest candidates for missing sources |
| `fontes` | none | the catalogue of sources |

An unknown parameter is refused. Defaults: `to` is now, `from` seven days earlier (one day for `lang_gap` and
`articles`).

### Views for SQL

| View | Content |
|---|---|
| `facta` | the uniform view over all sources, current version of every row, with `reliability` of the source |
| `facta_all` | every recorded version |
| `facta_asof(t)` | table macro: the state at time t |
| `facta_public` | rows whose licence allows publication as open data |
| `fama_events`, `fama_mentions`, `fama_gkg` | GDELT events (400 days), mentions (400 days), knowledge graph extract (30 days) |
| `fama_hourly_events`, `fama_hourly_geo`, `fama_hourly_theme` | permanent hourly counts; sum over rows, a slot writes partial counts |
| `kev_entries` | CISA catalogue, every version of an entry |
| `prov_runs`, `prov_raw` | runs with commit and inputs; fetched raw files with SHA-256 |
| `fontes`, `cells`, `quaestiones`, `licentiae` | catalogue, declared coverage cells, questions, licence flags |
| `indicators`, `tabula`, `specillum`, `drift`, `expectations` | results of the daily and monthly runs |

Columns of `facta`: `row_id, fons, domain, classis, iso3, adm1, h3_5, lat, lon, t_from, t_to, t_reported,
t_fetched, recorded_at, measure, value, unit, label, url, license, credibility, run_id, schema_version, dt,
reliability`. Filter on `dt` (the day a row entered the lake) to keep queries on large tables fast.

Never add up `value` across classes: group by `classis`.

## POST /relatio/check

Body: a draft assessment.

```json
{"title": "...", "quaestio": "q-...", "asof": "2026-11-18T12:00:00Z",
 "queries": {"n": "SELECT ..."},
 "hypotheses": [{"text": "...", "weakened_by": ["row_id or URL"]}, {"text": "...", "weakened_by": []}],
 "assumptions": ["..."], "text": "...", "results_hash": "optional, from an earlier check"}
```

Answer: `{"ok": bool, "problems": [...], "results_hash": "...", "results": {...}}`. Problems name missing
fields, probability words outside the seven fixed terms or without a number in their band, figures in the text
that appear in no returned row, and results that differ from the stored hash.

## The state document

`commit`, `rejected` (commit, time, reason, log tail of the last rejected commit, or null), `sandbox`
(`full`, `no-private-network` or `degraded`), `disk`, `memory`, `fontes` (per source: `state` of `ok`, `idle`,
`error`, `disturbed`, `over_budget`; the last result of each phase; drift findings; budget), `quaestiones`
(open, overdue, triggered, no_data, errors), `tabula` (covered, thin, blind, and the verdict per question),
`logs` (last 50 journal lines per unit).
