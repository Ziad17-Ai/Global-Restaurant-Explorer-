# Project Plan

> **Status:** Draft v0.4, a living document.
> **Last updated:** 2026-11-24

## 1. Purpose and objectives

**Problem.** Restaurant data is spread across datasets with inconsistent formats, missing values, duplicates, and different geographic representations, which makes it hard to search, compare, and explore across locations.

**Objectives**

1. Integrate restaurant data into one centralized, multi-source-capable MySQL database on Azure (delivering the Zomato dataset end-to-end as Increment 1, followed by additional sources in Increment 2).
2. Build automated, scheduled ETL pipelines using Bronze, Silver, and Gold layers with programmatic fetching, change detection, and incremental loads.
3. Implement catalogued data-quality checks (`docs/DATA_QUALITY_RULES.md`), quarantine invalid records instead of silently dropping them, and enforce a 15% quarantine safety gate.
4. Deliver a responsive Streamlit web app (`docs/UI_UX.md`) backed by FastAPI with filtering, an interactive map, and natural-language search.
5. Orchestrate the pipeline with Apache Airflow on per-source schedules.
6. Deploy the database and application on Microsoft Azure with centralized secrets (`docs/SECRETS.md`) and non-secret settings (`config/settings.toml`).
7. Document the system to the academy's standard.

**Success criteria**

- The pipeline fetches Zomato dynamically via the Kaggle API, runs end-to-end through Airflow with change detection and incremental upserts, logs every rejected/warned record with a rule name and reason, and enforces the 15% quarantine gate.
- The schema preserves per-record provenance (`source_id`, `source_restaurant_id`, `batch_id`, `match_group_id`) ready for Increment 2 source expansion, and integrates a second source once Increment 1 is complete.
- The three user-facing features work against real data through a public URL (or a demonstrated fallback if Azure access fails), meeting the 2-second typical search target (up to 100K restaurants, 5–20 concurrent users) and 95% initial availability goal.
- After refactoring completes, a new team member can set up the project from `README.md` and `.env.example` alone.

## 2. Incremental delivery strategy

To keep Agile increments small and shippable while refactoring incoming drafts (`_incoming/`) into the production repository layout:

- **Increment 1 (Current refactoring & baseline working software):** Refactor ETL, SQL, FastAPI, Streamlit, and Airflow into clean layered modules; dynamically ingest the Zomato dataset via the Kaggle API (`@weekly` change-checked schedule); apply the canonical cuisine vocabulary (`docs/CUISINE_VOCABULARY.md`) and 15% quality gate; wire Streamlit exclusively through `web/streamlit/api_client.py`.
- **Increment 2 (Multi-source expansion & post-refactoring hardening):** Integrate the second data source (S1), define its schema mapping contract, cross-source `match_group_id` matching rules, and license-aware routing; finalize full-stack `docker-compose.yml`, `README.md` §7 setup instructions, and expanded testability gates (`docs/TESTING.md`).

## 3. Scope tiers (MoSCoW)

**Must (MVP — Increment 1 baseline + core architecture)**

- M1: Zomato dataset fetched programmatically via Kaggle API through Bronze (Azure Blob / local fallback), Silver (cleaned MySQL tables), and Gold (views/spatial indexes)
- M2: Multi-source provenance schema (`source_metadata`, `source_id`, `match_group_id`) in Increment 1; second source integrated in Increment 2 (S1)
- M3: Data-quality rule catalogue (`docs/DATA_QUALITY_RULES.md`), quarantine table (`data_quality_issues`), and **15% quarantine rate gate**
- M4: Incremental loading & change detection (FR-D7: check source metadata/SHA-256 before download; `record_hash` upserts)
- M5: FastAPI endpoints (`GET /api/restaurants`, `/api/map/points`, `/api/meta/*`, `POST /api/search/nl`, `GET /api/health`) with parameterized queries and JSON structured logging
- M6: Responsive Streamlit filters, results list, and compatible map (`docs/UI_UX.md`), consuming FastAPI over HTTP
- M7: NLP search through Hugging Face (5s timeout) with vocabulary validation and rule-based fallback
- M8: Per-source scheduled Airflow DAG (`@weekly` change-checked for Zomato) using `AIRFLOW_CONN_*` environment connections
- M9: Centralized secrets (`.env.example` / Key Vault) and portable non-secret config (`config/settings.toml` + `constants.py`); MySQL on Azure, backend and Streamlit co-deployed on App Service
- M10: Documentation, README, demo

**Should**

- Airflow deployed on an Azure Linux VM
- Azure Key Vault references in production
- Pipeline status & per-rule quality endpoint (`GET /api/pipeline/status`, FR-A1) and status page
- Cross-source duplicate matching rules (Increment 2, once Source 2 lands)
- Unit tests for quality rules, architecture boundary tests (`tests/test_architecture.py`), and Streamlit `AppTest` smoke tests

**Could (low priority / deferred)**

- Full-stack local `docker-compose.yml` and expanded testability suite (`docs/TESTING.md`, coverage gates, contract tests) — scheduled immediately after refactoring completes
- Graceful maintenance message in Streamlit when FastAPI is unreachable
- Cross-source attribute enrichment (D-8) and external source category-to-cuisine mapping table (D-9)
- Data classification & `raw_payload` retention policy, SQL view complexity caps
- Virtual Network and private networking; Azure Monitor and Application Insights
- Arabic NLP queries; further sources and historical snapshots

**Cut rule:** if Must items are behind, cut from Could and Should first; Increment 1 (Zomato end-to-end) takes strict priority over Increment 2 additions. Feature freeze is 28 Nov.

**Out of scope:** owner accounts, B2B matching, in-app reviews, additional business types, coordinate/locality imputation.

## 4. Methodology: Agile (Scrum-lite)

- **Sprints:** one week each, with a planning session at the start (30 min), a short mid-week sync, and a review plus retrospective at the end.
- **Backlog:** a GitHub Projects board with one card per task; priorities match the MoSCoW tiers; requirement IDs from `docs/SRS.md`.
- **Spikes:** timeboxed investigations for open questions, with decision criteria and due dates. Results are recorded in a decision log.
- **Definition of Done:** merged by pull request with review, automated checks pass, docs and `.env.example` / `config/settings.toml` updated in the same PR.
- **Living documents:** each document carries a status header and change log.

## 5. Team and responsibilities

| Member | Role |
| -------- | ------ |
| Ziad Ahmed El Shamy | TBD |
| Ali Ahmed Ali Kassem | TBD |
| Yehia Nader Ali | TBD |
| Abdulrahman Salem | TBD |
| Ahmed Hany | TBD |
| Ziad Salah ElKady | TBD |

**Suggested role areas** (each person owns one area and one test area):

1. Ingestion, Kaggle dynamic fetch, change detection, and Bronze layer (Python, Blob Storage)
2. Cleaning, canonical cuisine normalization, Silver layer, quality rules & 15% gate
3. Database schema, incremental upserts, Gold layer, spatial indexes (MySQL)
4. FastAPI backend, `GET /api/health`, `/api/pipeline/status`, and NLP adapter
5. Streamlit web presentation (`docs/UI_UX.md`), `api_client.py`, and map
6. Airflow (`AIRFLOW_CONN_*`), centralized config (`config/settings.toml`), Azure deployment, CI

Everyone contributes to documentation and testing.

## 6. Spikes (open decisions)

| ID | Question | Due | Decision criteria | Fallback |
| ---- | ---------- | ----- | ------------------- | ---------- |
| S1 | Which additional source(s) and geographic data for Increment 2? | Increment 2 | Rows and category completeness for target cities (including Egypt), valid coordinates, license, ingestion effort | Deliver Increment 1 cleanly on Zomato; Overture Maps first candidate |
| S2 | Airflow: local Docker only, or Azure VM too? | Local by 18 Nov; VM decision 21 Nov | Setup time, reliability, cost, demo value | Airflow in Docker for the demo; scripts stay scheduler-agnostic |
| S3 | Which Hugging Face model and provider? | 18 Nov | Correct extraction rate on 30-50 sample queries, JSON reliability, <5s latency, free-tier limits | Rule-based parser using the controlled vocabulary |
| S4 | Azure access, credits, and cost | Sprint 1 | Working subscriptions, MySQL Flexible Server + App Service cost, budget alerts set | Local MySQL and Docker for the demo; document the limitation |

**S3 method:** write the sample queries and expected parameters first, then score each candidate model on them. Choose on measured results.

## 7. Iteration plan

**Sprint 0: 30-31 Oct (documentation)**

- Tasks: initial five documents; repository skeleton and board; role planning; Azure access check (S4).
- Deliverables: docs v0.2, repo structure.

**Break: 1-14 Nov (optional prep)**

- Toolchains (Python, Docker); Azure resource group and budget alert; Zomato dataset inspection (encoding, currencies, zero ratings, zero coordinates).

**Sprint 1: 15-21 Nov (data foundation and drafts)**

- Tasks: initial ETL, SQL, Airflow, FastAPI, and Streamlit prototypes (`_incoming/`); architecture and coding standards refinement.
- Deliverables: working prototypes and aligned specifications.

**Sprint 2: 22-28 Nov (Increment 1 refactoring, linkage, and deployment)**

- Tasks: finalize specs (`SECRETS.md`, `DATA_SOURCES.md`, `DATA_QUALITY_RULES.md`, `CUISINE_VOCABULARY.md`, `UI_UX.md`, `AGENTS.md`); refactor `_incoming/` drafts into `pipeline/`, `sql/`, `web/backend/`, `web/streamlit/`, and `config/settings.toml`; dynamic Kaggle fetch + `@weekly` change-checked Airflow DAG + 15% quality gate; co-deploy FastAPI and Streamlit; complete post-refactoring `README.md` §7 and Docker setup; start Increment 2 source integration if capacity allows. **Feature freeze 28 Nov.**
- Deliverables: cohesive, boundary-tested Increment 1 deployed and running end-to-end.

**Final: 29-30 Nov (hardening and delivery)**

- Tasks: bug fixes only; finalize README run instructions and test suite; demo rehearsal; record a backup demo video.
- Deliverables: final submission, demo, retrospective notes.

## 8. Risk register

| ID | Risk | Likelihood | Impact | Mitigation |
| ---- | ------ | ------------ | -------- | ------------ |
| R1 | Tight build window because of midterms | High | High | Zomato-first Increment 1, MoSCoW cut rule, feature freeze 28 Nov |
| R2 | Azure provisioning, credits, or cost problems | Medium | High | S4 budget alerts; zero-cost `AIRFLOW_CONN_*` env injection; local Docker fallback |
| R3 | Zomato data quirks (Latin-1 mojibake, shared `Dollar($)` label, 2,148 zero ratings, 499 zero coordinates) | High | Medium | Profiled in `DATA_SOURCES.md`; handled in `DATA_QUALITY_RULES.md` + 15% gate |
| R4 | No Egypt coverage in Zomato baseline | High | Medium | Honest UI coverage disclosure in Increment 1; Egypt source targeted in Increment 2 (S1) |
| R5 | Hugging Face limits, >5s latency, or invalid JSON | Medium | Medium | Adapter pattern, 5s timeout, caching, rule-based fallback |
| R6 | Airflow setup or refactoring integration friction | Medium | Medium | Local Docker first; `AIRFLOW_CONN_*` env vars; `tests/test_architecture.py` |
| R7 | License or terms violation | Low | High | Per-record source/license metadata; license routing before share-alike sources land |
| R8 | Skill gaps (SQL spatial, Streamlit 1.67, FastAPI layering, Airflow) | High | Medium | `AGENTS.md`, Streamlit official skills, `CODE_STYLE.md` worked examples |
| R9 | Scope creep | High | Medium | 100K-row ceiling, deferred non-critical items, change log |
| R10 | Overlap with existing public projects | Medium | Medium | Cite and differentiate (`docs/LITERATURE_REVIEW.md`); original code |

## 9. Communication and tooling

- Source control: GitHub with feature branches and pull requests (see `CONTRIBUTING.md`).
- Task tracking: GitHub Projects and Issues.
- Coding standards & agent navigation: `docs/CODE_STYLE.md`, `AGENTS.md`.

## 10. Deliverables checklist

- [x] Project plan (this document)
- [x] Literature review
- [x] SRS and system design (`SRS.md`, `ARCHITECTURE.md`, `DATA_SOURCES.md`, `DATA_QUALITY_RULES.md`, `CUISINE_VOCABULARY.md`, `SECRETS.md`, `UI_UX.md`)
- [ ] Refactored Bronze, Silver, Gold pipeline and MySQL database (Increment 1)
- [ ] Scheduled Airflow DAG with dynamic Kaggle fetch and 15% quality gate
- [ ] Refactored FastAPI + Streamlit web application with three features
- [ ] Architecture, quality-rule, and smoke tests (expanded `TESTING.md` post-refactoring)
- [ ] Post-refactoring `README.md` §7 run instructions, `docker-compose.yml`, and deployed link
- [ ] Final presentation and demo

## 11. Change log

| Date | Change | Reason |
|------|--------|--------|
| 2026-10-30 | v0.1 created | Initial draft |
| 2026-10-30 | v0.2: stack aligned to team proposal; calendar and scope tiers added | Team proposal and deadline constraints |
| 2026-11-23 | v0.3: confirmed Option A for Streamlit data access (calling FastAPI over HTTP with no database credentials) per `CODE_STYLE.md` CS-15 resolution | Architecture alignment |
| 2026-11-24 | v0.4: added two-increment Agile strategy (Zomato dynamic fetch first, Source 2 next); promoted incremental loads (M4/FR-D7) to Must and `/api/pipeline/status` to Should; added 15% quarantine gate, 100K/95% targets, `config/settings.toml` + `AIRFLOW_CONN_*`, and deferred post-refactoring Docker/README/testability items | Review report decisions |
