# Citrinitas: specification

What the system must do, permanently. A change to behaviour changes this file, its acceptance and the code in
the same pull request. Each requirement has a stable ID; a withdrawn ID is not reused. `C` requirements hold for
the whole system, `F` requirements for Fama, the first source.

**Story.** 2026-11-18, the owner: his own open source intelligence base with full analysis by geography, time
and domain; sources for a live picture, a historical picture and a view of the future, so that any question can
be answered; and a way to close every blind spot. The first request that day was narrower: bind GDELT
completely and on demand without loading the home automation system that displays it.

Citrinitas is the yellowing, the third stage of the alchemical opus between albedo and rubedo: the light in
which things become visible. Later alchemy often dropped the stage and counted three. A system about blind
spots is named after the stage that was overlooked. It is built as a lighthouse, not a watchtower: it shows
where things are, it does not watch persons.

## Parts

| Part | Name | Where |
|---|---|---|
| Core: store, lake, read-only door, state, upkeep | Athanor, the furnace that runs steadily | `citrinitas/athanor/` |
| Sources, one adapter each | Fontes | `citrinitas/fontes/`, catalogue in `catalog/fontes.yaml` |
| First source: GDELT 2.0 | Fama, the house where every report arrives | `citrinitas/fontes/fama.py` |
| Questions, indicators, expectations, assessments | Quaestiones | `citrinitas/quaestiones/`, register in `catalog/quaestiones.yaml` |
| Coverage matrix | Tabula | `citrinitas/tabula/` |
| Probe for unknown gaps | Specillum | `citrinitas/specillum/` |
| Installation on a Proxmox LXC | | `deploy/` |

## Requirements: the system

**C1 Three keys on every fact.** Every row carries place, time and domain. Place is the country as ISO 3166-1
alpha-3, the first administrative level, and for coordinates the H3 cell at resolution 5. Time is the start and
end of what the fact refers to in UTC, kept apart from the time of reporting and the time of fetching. The keys
are set when a row is loaded, so that any source can be cut against any other without mapping at query time.

**C2 Fixed domains.** security, politics, economy, finance, energy, climate, health, food, population, network,
mobility, space, science, information, society. A new domain is added only when a source fits none.

**C3 Four classes.** Every fact has exactly one class: `measured` (an instrument or counter), `official` (an
authority or a party to a conflict states it), `reported` (media report it), `expected` (markets, forecasts,
models, scenarios). A derived figure names the classes of its sides; different classes are never added or
averaged into one number.

**C4 Origin on every row.** Every row carries its source, fetch time, licence and, where the source has one, the
link to the evidence.

**C5 Objects and links.** Besides series and events the core holds places, actors, documents and expectations
as objects with identifiers: states by ISO 3166, organisations and public offices by Wikidata, companies by
LEI. Links are typed and carry their origin.

**C6 Three times per domain.** For every domain the catalogue names sources for the live picture, the historical
picture and the future, the future split into projection, model, expectation and scenario.

**C7 Coverage is measured.** The matrix domain x level (world, country, region, place) x time (live, historic,
future) x class is computed from the catalogue and the lake. A cell without any observed class is blind; a cell
with one source, or with reports only, is thin. The matrix is also read per question.

**C8 A probe for unknown gaps.** Where reporting is dense and no measured or official fact exists, a source is
missing; the probe ranks these places per domain. It also ranks countries whose languages yield few documents
per inhabitant.

**C9 Access by caller.** Cards, automations and scripts ask through named templates. An analyst may also ask
with SQL over a connection that can only read: one SELECT, 2 GB of memory, 60 seconds, 5 000 rows, no file
outside the lake.

**C10 A source fails alone.** If a source fails, the others keep running; its error stands in the state
document.

**C11 No private persons.** Actors are states, organisations and persons in public office. Posts from open
social networks are stored only as counts by term, place and time, never by account. No object describes a
private person.

**C12 The licence decides what leaves.** Every source carries its licence in the catalogue. What may only be
used non-commercially or under the same licence stays inside.

**C13 Backup follows repeatability.** What the provider archives is not backed up. What exists only live is
backed up daily.

**C14 Displays hold numbers only.** A client that keeps history, such as a home automation system, stores
numeric values and asks for everything else at run time.

**C15 No alert.** No value of Citrinitas sends a message. Indicators and anomalies are state to be read. A
display that pushes on attention becomes itself a means of steering attention.

**C16 New code runs only after a green self-test.** Each commit is unpacked into its own directory and tested
there; the services switch to it only when the test passes and the API answers with the new commit. Otherwise
the previous commit keeps running and the state document names the rejected one.

**C17 The state document replaces the shell.** One request returns the running commit, the last rejected
commit, disk, memory, the sandbox level, the state of every source and the last 50 journal lines of every
unit.

**C18 Questions steer collection.** Every active source refers to at least one question in the register. A
source without a question only fills storage.

**C19 An indicator has a threshold.** Every question names observable indicators, each with a query, a
threshold, a direction and a base rate. Evaluated, an indicator has a value or the state `no_data`.

**C20 Two time axes.** Every row carries the time it refers to and the time it was recorded. A correction is a
new row; `facta` shows the newest version, `facta_asof(t)` what was known at time t.

**C21 Provenance.** Every row carries a run ID; the run names the code commit, its start, and its input files
with SHA-256.

**C22 Feedback closes questions.** Every question has a due date on which it is answered, extended or dropped;
overdue questions stand in the state document. Every quarter each source reports which questions it served.

**C23 Source and information are rated apart.** Every source has a reliability from A to F with a reason; every
fact a credibility from 1 to 6. The two are never combined into one value.

**C24 Confirmation across classes.** A fact reaches credibility 1 or 2 only when an independent source of
another class supports it. Until then it is 6, not judged.

**C25 Entities are linked, not merged.** Entity resolution writes `same_as` links with a probability and a run
ID and changes no source row.

**C26 Schema with a version.** Every row carries the schema version. A schema change comes with a migration
and a test that reads the oldest and the newest partition through the same view.

**C27 Anomaly against a baseline only.** A series stands out only against the baseline of the same source,
measured as a share of that source's total. Twice the volume at the same share is no anomaly.

**C28 Drift becomes a state.** Row count, schema hash and null share are measured per source, table and day. A
deviation marks the source `disturbed`. A file of the wrong shape is rejected instead of being loaded as nulls.

**C29 Expectations are resolved.** Every expectation is stored with probability, due date and resolution
criterion, and scored with the Brier score after the date.

**C30 Fixed words of probability.** Assessments use only seven terms with their bands and state the number:
almost no chance 1 to 5 %, very unlikely 5 to 20 %, unlikely 20 to 45 %, roughly even chance 45 to 55 %,
likely 55 to 80 %, very likely 80 to 95 %, almost certain 95 to 99 %.

**C31 Every figure has a row.** Every figure in an assessment appears in a row returned by one of its queries.

**C32 A counter-hypothesis.** Every assessment names at least two hypotheses, its assumptions, and the evidence
that weakens each hypothesis.

**C33 Stories with a stable ID.** Events and articles are bundled into stories and chained across days; counts
by story and by event are shown apart.

**C34 Coordination as a count only.** Near-identical texts or placements across outlets per time window are
counted and never attributed to an account or a person.

**C35 Persons only in a public role.** A person is an object only if Wikidata records a public office, and only
in relation to that office.

**C36 The licence is inherited.** A derived row carries every restriction of its inputs; the open export
contains no row that is share-alike, non-commercial, no-derivatives or otherwise restricted.

**C37 The parser has no network and no rights.** Foreign files are fetched in one unit and parsed in another
that has no network and can write only below the data home, with caps on memory, run time and unpacked size.

**C38 Raw data with a hash.** Every fetched raw file is logged with SHA-256, URL and fetch time. Every web page
cited in an assessment has an archive snapshot.

**C39 An assessment is reproducible.** It is stored as its queries plus a point in time; the same queries at
that time yield the same figures.

**C40 Earth observation only on a question.** Scenes are requested only for areas of open questions; only
derived values per H3 cell are stored.

**C41 Search without another service.** Full-text and vector search run as DuckDB extensions on the lake.

**C42 A budget per source.** Disk, run time and download volume of every source are measured daily against its
budget in the catalogue.

## Requirements: Fama

**F1 One fetch.** Every quarter of an hour Fama reads the two update lists and fetches each new file once,
checked against the MD5 of the list.

**F2 Gaps.** Missing quarter hours of the last 24 hours are fetched newest first, at most twelve per run and
stream. A file that answers 404 is asked again for six hours and then counts as empty.

**F3 A stream stands alone.** If the newest file of a stream is older than three hours, the state names that
stream; the other keeps running.

**F4 What is kept.** Events and mentions of both streams completely for 400 days. Of the GKG a column extract
for 30 days: time, outlet, URL, themes, organisations, locations, tone, language. Person names are not kept.
Hourly counts by country, language and theme are kept permanently.

**F5 Disk limit.** Above 80 % disk use the oldest GKG days are deleted, then the oldest events and mentions;
hourly counts never.

**F6 Templates.** `series`, `ranking`, `lang_gap`, `articles`, `anomalies`, `provenance`, `coverage`,
`indicators`, `probe`, `fontes`, `status`, each with typed parameters, at most 20 seconds and 500 rows.

**F7 History with a budget.** A request before the local window goes to the public GDELT tables in BigQuery,
always with a partition filter and a column list; a dry run measures the bytes, and above 800 GB in a calendar
month the request is refused.

**F8 One door.** All requests pass the HTTP API with a bearer token; without it only `/health` answers.

**F9 Numbers only in the display.** See C14.

**F10 Reports stay reports.** Every Fama row is class `reported`. No GDELT value stands on the measured side of
a derived signal.

**F11 No alert.** See C15.

**F12 Apart from the display.** The node keeps running when the system that displays it restarts.

## What does not follow

- No closed sources: nothing that needs a paid account, a login to closed networks or a way around a block.
  What open sources cannot show is named, so that missing data is not read as nothing happening.
- No automatic interpretation: Citrinitas returns facts with class and origin; meaning is made in an assessment.
- No profiles of persons, by design of the data model (C11, C34, C35).

## Acceptance

Automatic, in `tests/`, run by `python -m citrinitas selftest` on every install and in CI: C1, C2, C3, C4, C7,
C8, C9, C10, C11, C17, C18, C19, C20, C21, C22, C23, C27, C28, C29, C30, C31, C32, C35, C36, C37, C39, C42,
F1, F2, F3, F4, F5, F6, F8, F10. `scripts/spec_check.py` checks that every ID marked built or partial has a
`Spec <ID>` marker in code or tests.

By hand on the node after installation: `GET /status` names the commit of the branch and a sandbox level
(C16, C17, C37, F12); a commit with a failing test is rejected and named there while the previous one keeps
running (C16); two fetch runs in a row fetch no file twice (F1); no unit sends anything (C15, F11).

By judgement on every change: a new source names domain, class, levels, times, licence, reliability,
question and budget (C2, C3, C6, C12, C18, C23, C42); it stores no account and no private person (C11, C34).

Not yet built, with the acceptance to be written when built: C5, C13, C24, C25, C33, C34, C40, C41, F7.
Outside this repository, in the client that displays values: C14, F9.

## Status

| Status | IDs |
|---|---|
| built, tested | C1 C2 C3 C4 C7 C9 C10 C11 C12 C15 C17 C18 C19 C20 C21 C23 C27 C28 C29 C30 C31 C32 C35 C36 C39 C42 F1 F2 F3 F4 F6 F8 F10 F11 |
| partial | C6 (the catalogue declares times; future sources are planned) · C8 (probe by reporting density; documents per inhabitant planned) · C16 (built; first run on a node pending) · C22 (due dates and overdue state; quarterly source report planned) · C26 (version on every row; migration test planned) · C37 (size cap tested; unit sandbox pending on a node) · C38 (raw hash log; archive snapshots planned) · F5 (pruning tested; disk limit pending on a node) · F12 (pending on a node) |
| planned | C5 C13 C24 C25 C33 C34 C40 C41 F7 |
| external | C14 F9 |

Deviation from C1 as written: the first administrative level is stored as the code of the source (for Fama the
GDELT ADM1 code) until the mapping to geoBoundaries is built.

## Decided

- 2026-11-18: one node for all open sources, DuckDB over Parquet, Python under systemd, no container runtime.
- 2026-11-18: keys for place are set at load time, not at query time.
- 2026-11-18: read-only SQL for analysts next to templates: templates answer only foreseen questions.
- 2026-11-18: person names from GDELT are dropped at parse time. The first draft kept the GKG person column;
  that contradicted C11.
- 2026-11-18: code under Apache-2.0, own derived data under CC0, source data under their own licences. No
  "ethical" licence: responsibility lies in the data model, which has no person objects and no accounts.
- 2026-11-18: no write access through the API. The node reads the world and answers; it takes no orders.
