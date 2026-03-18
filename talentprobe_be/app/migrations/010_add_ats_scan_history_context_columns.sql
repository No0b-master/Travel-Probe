ALTER TABLE ats_scan_history
    ADD COLUMN resume_file_type VARCHAR(16) NULL AFTER resume_file_name,
    ADD COLUMN resume_text_snapshot LONGTEXT NULL AFTER industry,
    ADD COLUMN job_description_snapshot LONGTEXT NULL AFTER resume_text_snapshot;
