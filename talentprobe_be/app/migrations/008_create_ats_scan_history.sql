CREATE TABLE IF NOT EXISTS ats_scan_history (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    resume_id BIGINT NULL,
    resume_file_name VARCHAR(255) NULL,
    target_role VARCHAR(255) NULL,
    industry VARCHAR(255) NULL,
    overall_score DECIMAL(5,2) NOT NULL,
    matched_keywords_count INT NOT NULL DEFAULT 0,
    missing_keywords_count INT NOT NULL DEFAULT 0,
    section_gaps_count INT NOT NULL DEFAULT 0,
    summary VARCHAR(1024) NOT NULL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(resume_id) REFERENCES user_resumes(id) ON DELETE SET NULL,
    INDEX idx_ats_scan_history_user_created (user_id, created_at),
    INDEX idx_ats_scan_history_user_score (user_id, overall_score)
) ENGINE=InnoDB;
