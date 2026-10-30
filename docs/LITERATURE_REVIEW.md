# Literature Review

> **Status:** Draft v0.2, a living document. Entries marked **[VERIFY]** come from quick preliminary reading and must be re-read and rewritten in the team's own words before submission. Do not cite anything you have not read.
> **Last updated:** 2026-10-30

## 1. Purpose and scope

This review answers three questions:
1. What products and projects already solve similar problems (related work)?
2. What data sources exist, and what are their strengths, limits, and licenses?
3. What technical approaches support our pipeline (layered storage, reconciling sources, orchestration, translating natural language into filters)?

It then states where our project sits and what it does differently.

## 2. Related work

### 2.1 Consumer place-discovery products
Large platforms such as Google Maps, Zomato, and TripAdvisor already let users search for restaurants by location, cuisine, and rating, using proprietary data and user-generated reviews. **Implication:** a search-only app is not a differentiator. Our contribution has to be the data engineering: multi-source ingestion, quality management, and a documented, reproducible pipeline. **[VERIFY: check current features and regional coverage, including Egypt.]**

### 2.2 Commercial location-intelligence tools
Vendors such as xmap.ai, Maptitude, and TargomoLOOP, and free tools such as HorecaStore's "Restaurant Site Finder," offer competitor mapping and site analysis for food businesses. They target business users, are generally proprietary, and do not publish their methodology. **[VERIFY: read each vendor's own description.]**

### 2.3 Open-source and student projects
A public GitHub project, "zomato-ai-data-engineering-end-to-end-project" (author: darshilparmar), was reviewed by the team. Preliminary notes: a food-delivery order-analytics pipeline over generated order data, using cloud storage, a cloud warehouse, dbt, and Airflow, with an AI layer, and a video walkthrough. **[VERIFY: re-read the repository and summarize accurately.]**
**Relationship to our work:** it shares a theme (Zomato, food, data engineering, Airflow) but differs in data (real, multi-source restaurant records vs. generated orders), database (MySQL on Azure), product (searchable web application with map and NLP search), and design. We cite it as prior art, do not reuse its code or name, and describe our differences explicitly.

### 2.4 Natural-language interfaces
LLM services (for example, models served through Hugging Face Inference Providers) can extract structured fields from free text. Two broad approaches exist: constrained extraction into a fixed schema, and open-ended query generation. We choose constrained extraction. **[VERIFY: add 2-3 references on structured output or slot filling after reading them.]**

## 3. Data sources review

| Source | What it offers | Update pattern | License notes (verify with provider) | Limits for our use |
|--------|---------------|----------------|--------------------------------------|--------------------|
| Zomato dataset (Kaggle) | About 9.5k restaurants: cuisines, cost for two, currency, ratings, votes, delivery/booking flags, coordinates | Static snapshot | Check the dataset page | Concentrated in India; as far as we know no Egypt; likely quirks to verify: file encoding, mixed currencies, zero ratings for unrated places, invalid coordinates **[VERIFY on the real file]** |
| Overture Maps Places | Global places: names, categories, locations, addresses, contacts | Periodic releases; GeoParquet on AWS and Azure | Multi-license: Foursquare-sourced records Apache 2.0, others CDLA 2.0; keep the per-record source and license | No ratings; category quality varies; `operating_status` was set to "open" for all records in the Sept 2025 release, so check later releases |
| Foursquare OS Places | 100M+ places, 1000+ categories | Monthly refresh | Apache 2.0, attribution notice required | Now gated on Hugging Face (contact info required); open version appears to withhold richer attributes **[VERIFY]**; includes closure and refresh dates |
| OpenStreetMap | Community-edited places with free-form tags (cuisine, diet) | Continuous; regional extracts refreshed regularly | ODbL (attribution and share-alike) **[VERIFY]** | Tag completeness in Egypt uneven; normalization needed |
| Administrative boundaries | District and governorate polygons | Occasional | Depends on provider | Accuracy varies |
| Yelp Open Dataset | Businesses, ratings, review text | Static | Academic terms; check coursework suitability **[VERIFY]** | US/Canada metros only |
| Commercial APIs (e.g., Google Places) | Rich, current data | Live | Terms commonly restrict storing and caching **[VERIFY]** | Likely incompatible with a persistent warehouse |

**Findings so far:** (1) the baseline dataset gives ratings but little Egypt coverage; (2) the open place datasets give Egypt coverage but no ratings; (3) combining them requires reconciling schemas, categories, and duplicates, which is the central data engineering task of this project.

## 4. Technical background

### 4.1 Layered (medallion) pipelines
Keeping immutable raw data (Bronze), cleaned and standardized data (Silver), and consumption-ready data (Gold) separates concerns, supports reprocessing, and makes quality problems traceable. **[VERIFY: cite a primary description you have read.]**

### 4.2 Integrating heterogeneous sources
Deciding which records from different sources describe the same real-world place is the record-linkage (entity resolution) problem. The classic probabilistic formulation is Fellegi and Sunter (1969). In practice, place matching combines name similarity, geographic distance, and category agreement. **Decision for us:** TBD (rule-based matching first).

### 4.3 Workflow orchestration
Apache Airflow expresses pipelines as DAGs of tasks with dependencies, schedules, retries, and logs. Good practice is to keep tasks small and idempotent and keep business logic outside DAG files. **[VERIFY: cite the official documentation after reading.]**

### 4.4 Geospatial serving
Search by area and map display need valid coordinates, mapping places to localities and cities, and indexes for bounding-box queries. **Decision for us:** TBD (see `docs/ARCHITECTURE.md`, decision D-5).

### 4.5 Safe natural-language search
Allowing a model to produce executable SQL creates injection and correctness risks. Constraining the model to fill a fixed parameter schema, validating the output, and using parameterized queries avoids this. Evaluation uses a labeled set of sample queries.

## 5. Gap and positioning

- Restaurant search is a solved consumer problem and competitor mapping is a solved commercial problem.
- What remains is a **transparent, reproducible, multi-source pipeline** with documented data quality, exposed through a simple application.
- Our contribution: layered ingestion and reconciliation, quarantine and quality tracking, per-record source provenance, orchestration with Airflow, and a safe NLP-to-filter layer, all deployed on Azure.
- We do not claim to outperform commercial products. We claim an auditable pipeline and an honest account of coverage and limits.

## 6. References

Replace with properly formatted citations as items are read.

1. Fellegi, I. P., & Sunter, A. B. (1969). A theory for record linkage. *Journal of the American Statistical Association*, 64(328), 1183-1210.
2. Overture Maps Foundation documentation: Places guide and release notes. (retrieved: TBD)
3. Foursquare documentation: FSQ OS Places schema and release notes. (retrieved: TBD)
4. OpenStreetMap Foundation: copyright and license page. (retrieved: TBD)
5. Apache Airflow documentation. (retrieved: TBD)
6. Microsoft Azure documentation: Database for MySQL Flexible Server, Blob Storage, App Service, Static Web Apps. (retrieved: TBD)
7. Hugging Face documentation: Inference Providers. (retrieved: TBD)
8. Repository: darshilparmar/zomato-ai-data-engineering-end-to-end-project (GitHub). (retrieved: TBD)
9. Vendor pages: xmap.ai, Maptitude, TargomoLOOP. (retrieved: TBD)
10. TODO: 3-5 academic or technical references on entity resolution, data quality, and structured extraction.

## 7. Change log

| Date | Change |
|------|--------|
| 2026-10-30 | v0.1 created |
| 2026-10-30 | v0.2: aligned to team proposal (Zomato baseline, Airflow, Hugging Face, Azure) |
