-- ============================================================================
-- Migration 001: Additive ETL Metadata, Data Quality & Quarantine Tables
-- Target Database: zomato_restaurant_explorer (MySQL 8.0+ / InnoDB / utf8mb4)
-- Safety: Strictly additive (CREATE TABLE IF NOT EXISTS). Never drops or
--         modifies any of the 8 existing core tables or v_restaurant_explorer.
-- ============================================================================

CREATE TABLE IF NOT EXISTS etl_schema_migrations (
    migration_version VARCHAR(50)  NOT NULL,
    migration_name    VARCHAR(150) NOT NULL,
    applied_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (migration_version)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Tracks applied additive ETL database migrations';

CREATE TABLE IF NOT EXISTS etl_ingestion_batches (
    batch_id              CHAR(36)        NOT NULL,
    source_name           VARCHAR(100)    NOT NULL,
    source_file_name      VARCHAR(255)    NOT NULL,
    source_file_path      VARCHAR(500)    NOT NULL,
    source_file_hash      CHAR(64)        NOT NULL,
    source_file_size      BIGINT UNSIGNED NOT NULL,
    source_row_count      INT UNSIGNED    NOT NULL DEFAULT 0,
    accepted_row_count    INT UNSIGNED    NOT NULL DEFAULT 0,
    rejected_row_count    INT UNSIGNED    NOT NULL DEFAULT 0,
    ingestion_started_at  DATETIME        NOT NULL,
    ingestion_finished_at DATETIME        NULL,
    ingestion_status      VARCHAR(32)     NOT NULL,
    storage_backend       VARCHAR(32)     NOT NULL DEFAULT 'local',
    bronze_uri            VARCHAR(500)    NULL,
    error_message         TEXT            NULL,
    created_at            TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (batch_id),
    KEY idx_etl_batches_hash_status (source_file_hash, ingestion_status),
    KEY idx_etl_batches_source_time (source_name, ingestion_started_at DESC),
    CONSTRAINT chk_etl_batches_status
        CHECK (ingestion_status IN ('RUNNING', 'SUCCESS', 'FAILED', 'PARTIAL_SUCCESS', 'SKIPPED'))
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Tracks every Bronze/Silver ingestion batch, checksum, and counts';

CREATE TABLE IF NOT EXISTS etl_pipeline_runs (
    run_id            CHAR(36)     NOT NULL,
    batch_id          CHAR(36)     NOT NULL,
    stage             VARCHAR(32)  NOT NULL,
    started_at        DATETIME     NOT NULL,
    finished_at       DATETIME     NULL,
    extracted_count   INT UNSIGNED NOT NULL DEFAULT 0,
    transformed_count INT UNSIGNED NOT NULL DEFAULT 0,
    accepted_count    INT UNSIGNED NOT NULL DEFAULT 0,
    rejected_count    INT UNSIGNED NOT NULL DEFAULT 0,
    inserted_count    INT UNSIGNED NOT NULL DEFAULT 0,
    updated_count     INT UNSIGNED NOT NULL DEFAULT 0,
    unchanged_count   INT UNSIGNED NOT NULL DEFAULT 0,
    dq_issue_count    INT UNSIGNED NOT NULL DEFAULT 0,
    status            VARCHAR(32)  NOT NULL,
    error_message     TEXT         NULL,
    created_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id),
    KEY idx_etl_runs_batch_stage (batch_id, stage),
    CONSTRAINT fk_etl_runs_batch
        FOREIGN KEY (batch_id) REFERENCES etl_ingestion_batches (batch_id)
        ON UPDATE RESTRICT
        ON DELETE CASCADE,
    CONSTRAINT chk_etl_runs_stage
        CHECK (stage IN ('EXTRACT', 'BRONZE', 'VALIDATE', 'TRANSFORM', 'SILVER_LOAD', 'GOLD_REFRESH', 'FULL_PIPELINE')),
    CONSTRAINT chk_etl_runs_status
        CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED', 'PARTIAL_SUCCESS', 'SKIPPED'))
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Tracks stage-level execution metrics and statuses for each ETL run';

CREATE TABLE IF NOT EXISTS etl_data_quality_issues (
    issue_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    batch_id          CHAR(36)        NOT NULL,
    restaurant_id     INT UNSIGNED    NULL,
    source_row_number INT UNSIGNED    NOT NULL,
    column_name       VARCHAR(64)     NOT NULL,
    issue_type        VARCHAR(64)     NOT NULL,
    severity          VARCHAR(16)     NOT NULL,
    original_value    VARCHAR(500)    NULL,
    issue_description VARCHAR(500)    NOT NULL,
    detected_at       TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (issue_id),
    KEY idx_dq_batch_severity (batch_id, severity),
    KEY idx_dq_issue_type     (issue_type),
    KEY idx_dq_restaurant     (restaurant_id),
    CONSTRAINT fk_dq_batch
        FOREIGN KEY (batch_id) REFERENCES etl_ingestion_batches (batch_id)
        ON UPDATE RESTRICT
        ON DELETE CASCADE,
    CONSTRAINT chk_dq_severity
        CHECK (severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL'))
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Granular data quality findings detected during Silver validation';

CREATE TABLE IF NOT EXISTS etl_quarantine_records (
    quarantine_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    batch_id          CHAR(36)        NOT NULL,
    source_row_number INT UNSIGNED    NOT NULL,
    restaurant_id     INT UNSIGNED    NULL,
    raw_record        JSON            NOT NULL,
    rejection_reason  VARCHAR(500)    NOT NULL,
    quarantine_status VARCHAR(20)     NOT NULL DEFAULT 'OPEN',
    created_at        TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (quarantine_id),
    KEY idx_quarantine_batch_status (batch_id, quarantine_status),
    KEY idx_quarantine_restaurant   (restaurant_id),
    CONSTRAINT fk_quarantine_batch
        FOREIGN KEY (batch_id) REFERENCES etl_ingestion_batches (batch_id)
        ON UPDATE RESTRICT
        ON DELETE CASCADE,
    CONSTRAINT chk_quarantine_status
        CHECK (quarantine_status IN ('OPEN', 'REVIEWED', 'RESOLVED', 'DISCARDED'))
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Quarantined invalid source records with full JSON payload and rejection reason';

INSERT IGNORE INTO etl_schema_migrations (migration_version, migration_name)
VALUES ('001', 'create_etl_metadata');
