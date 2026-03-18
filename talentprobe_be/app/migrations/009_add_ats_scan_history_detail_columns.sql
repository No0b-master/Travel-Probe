ALTER TABLE ats_scan_history
    ADD COLUMN breakdown_json LONGTEXT NULL AFTER overall_score,
    ADD COLUMN matched_keywords_json LONGTEXT NULL AFTER breakdown_json,
    ADD COLUMN missing_keywords_json LONGTEXT NULL AFTER matched_keywords_json,
    ADD COLUMN section_gaps_json LONGTEXT NULL AFTER missing_keywords_json,
    ADD COLUMN recommendations_json LONGTEXT NULL AFTER section_gaps_json;
