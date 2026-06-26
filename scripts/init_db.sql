-- PostgreSQL Database Initialization Script
-- 命名规约：表名单数、字段全小写、布尔字段 is_xxx、审计字段 create_by/update_by/create_time/update_time

-- ============================================================
-- 1. alarm_record (告警记录)
-- ============================================================
CREATE TABLE IF NOT EXISTS alarm_record (
    id BIGSERIAL PRIMARY KEY,
    stream_url TEXT NOT NULL,
    stream_id VARCHAR(64),
    alarm_type VARCHAR(32) NOT NULL,
    confidence FLOAT4 NOT NULL,
    image_path TEXT NOT NULL,
    track_id INTEGER,
    class_name VARCHAR(64),
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    create_by VARCHAR(64),
    update_by VARCHAR(64),
    create_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alarm_record_stream_id ON alarm_record(stream_id);
CREATE INDEX IF NOT EXISTS idx_alarm_record_type ON alarm_record(alarm_type);
CREATE INDEX IF NOT EXISTS idx_alarm_record_time ON alarm_record USING brin(detected_at);

-- ============================================================
-- 2. annotation_image (标注图片)
-- ============================================================
CREATE TABLE IF NOT EXISTS annotation_image (
    id BIGSERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    width INTEGER,
    height INTEGER,
    source VARCHAR(32) DEFAULT 'upload',
    dataset_name VARCHAR(128),
    split VARCHAR(16) DEFAULT 'train',
    is_annotated BOOLEAN DEFAULT FALSE,
    box_count INTEGER DEFAULT 0,
    create_by VARCHAR(64),
    update_by VARCHAR(64),
    create_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_annotation_image_filename ON annotation_image(filename);
CREATE INDEX IF NOT EXISTS idx_annotation_image_dataset ON annotation_image(dataset_name);
CREATE INDEX IF NOT EXISTS idx_annotation_image_annotated ON annotation_image(is_annotated);

-- ============================================================
-- 3. annotation_box (标注框)
-- ============================================================
CREATE TABLE IF NOT EXISTS annotation_box (
    id BIGSERIAL PRIMARY KEY,
    image_id BIGINT NOT NULL,
    class_id INTEGER NOT NULL,
    class_name VARCHAR(64) NOT NULL,
    cx FLOAT8 NOT NULL,
    cy FLOAT8 NOT NULL,
    bw FLOAT8 NOT NULL,
    bh FLOAT8 NOT NULL,
    confidence FLOAT4,
    annotator VARCHAR(64),
    create_by VARCHAR(64),
    update_by VARCHAR(64),
    create_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_annotation_box_image ON annotation_box(image_id);
CREATE INDEX IF NOT EXISTS idx_annotation_box_class ON annotation_box(class_name);

-- ============================================================
-- 4. dataset (数据集)
-- ============================================================
CREATE TABLE IF NOT EXISTS dataset (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL UNIQUE,
    description TEXT,
    class_mapping JSONB NOT NULL,
    total_images INTEGER DEFAULT 0,
    train_count INTEGER DEFAULT 0,
    val_count INTEGER DEFAULT 0,
    test_count INTEGER DEFAULT 0,
    create_by VARCHAR(64),
    update_by VARCHAR(64),
    create_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 5. sys_user (用户)
-- ============================================================
CREATE TABLE IF NOT EXISTS sys_user (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name VARCHAR(128),
    role VARCHAR(16) DEFAULT 'viewer',
    is_active BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMPTZ,
    create_by VARCHAR(64),
    update_by VARCHAR(64),
    create_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sys_user_username ON sys_user(username);

-- ============================================================
-- 6. sys_session (会话)
-- ============================================================
CREATE TABLE IF NOT EXISTS sys_session (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    token VARCHAR(128) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    create_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sys_session_token ON sys_session(token);

-- ============================================================
-- 7. detection_result (检测结果)
-- ============================================================
CREATE TABLE IF NOT EXISTS detection_result (
    id BIGSERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    image_path TEXT,
    model_name VARCHAR(32) NOT NULL,
    confidence_threshold FLOAT4 NOT NULL,
    inference_time_ms FLOAT4,
    image_width INTEGER,
    image_height INTEGER,
    detections_count INTEGER DEFAULT 0,
    user_id BIGINT,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    create_by VARCHAR(64),
    update_by VARCHAR(64),
    create_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_detection_result_model ON detection_result(model_name);
CREATE INDEX IF NOT EXISTS idx_detection_result_time ON detection_result USING brin(detected_at);

-- ============================================================
-- 8. detection_box (检测框)
-- ============================================================
CREATE TABLE IF NOT EXISTS detection_box (
    id BIGSERIAL PRIMARY KEY,
    result_id BIGINT NOT NULL,
    class_id INTEGER NOT NULL,
    class_name VARCHAR(64) NOT NULL,
    confidence FLOAT4 NOT NULL,
    bbox_x1 FLOAT8 NOT NULL,
    bbox_y1 FLOAT8 NOT NULL,
    bbox_x2 FLOAT8 NOT NULL,
    bbox_y2 FLOAT8 NOT NULL,
    create_by VARCHAR(64),
    update_by VARCHAR(64),
    create_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_detection_box_result ON detection_box(result_id);
CREATE INDEX IF NOT EXISTS idx_detection_box_class ON detection_box(class_name);

-- ============================================================
-- 9. stream_config (流配置)
-- ============================================================
CREATE TABLE IF NOT EXISTS stream_config (
    id BIGSERIAL PRIMARY KEY,
    stream_id VARCHAR(64) NOT NULL UNIQUE,
    stream_url TEXT NOT NULL,
    alarm_types JSONB NOT NULL DEFAULT '["helmet","fire","intrusion"]',
    status VARCHAR(16) DEFAULT 'idle',
    error_message TEXT,
    frame_count INTEGER DEFAULT 0,
    alarm_count INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ,
    stopped_at TIMESTAMPTZ,
    create_by VARCHAR(64),
    update_by VARCHAR(64),
    create_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_stream_config_status ON stream_config(status);

-- ============================================================
-- 10. operation_log (操作日志)
-- ============================================================
CREATE TABLE IF NOT EXISTS operation_log (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    username VARCHAR(64),
    action VARCHAR(64) NOT NULL,
    target_type VARCHAR(32),
    target_id VARCHAR(64),
    detail JSONB,
    ip_address VARCHAR(64),
    create_by VARCHAR(64),
    update_by VARCHAR(64),
    create_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_operation_log_user ON operation_log(user_id);
CREATE INDEX IF NOT EXISTS idx_operation_log_time ON operation_log USING brin(create_time);
CREATE INDEX IF NOT EXISTS idx_operation_log_action ON operation_log(action);

-- ============================================================
-- 11. system_config (系统配置)
-- ============================================================
CREATE TABLE IF NOT EXISTS system_config (
    id BIGSERIAL PRIMARY KEY,
    config_key VARCHAR(128) NOT NULL UNIQUE,
    config_value TEXT NOT NULL,
    config_type VARCHAR(16) DEFAULT 'string',
    description TEXT,
    create_by VARCHAR(64),
    update_by VARCHAR(64),
    create_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 12. training_record (训练记录)
-- ============================================================
CREATE TABLE IF NOT EXISTS training_record (
    id BIGSERIAL PRIMARY KEY,
    model_name VARCHAR(64) NOT NULL,
    dataset_name VARCHAR(128),
    epochs INTEGER,
    batch_size INTEGER,
    img_size INTEGER,
    best_map50 FLOAT8,
    best_map50_95 FLOAT8,
    model_path TEXT,
    config JSONB,
    status VARCHAR(16) DEFAULT 'pending',
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    create_by VARCHAR(64),
    update_by VARCHAR(64),
    create_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_training_record_model ON training_record(model_name);
CREATE INDEX IF NOT EXISTS idx_training_record_status ON training_record(status);

-- ============================================================
-- Trigger: auto-update update_time
-- ============================================================
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_annotation_image_modtime') THEN
        CREATE TRIGGER update_annotation_image_modtime BEFORE UPDATE ON annotation_image FOR EACH ROW EXECUTE FUNCTION update_modified_column();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_annotation_box_modtime') THEN
        CREATE TRIGGER update_annotation_box_modtime BEFORE UPDATE ON annotation_box FOR EACH ROW EXECUTE FUNCTION update_modified_column();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_dataset_modtime') THEN
        CREATE TRIGGER update_dataset_modtime BEFORE UPDATE ON dataset FOR EACH ROW EXECUTE FUNCTION update_modified_column();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_sys_user_modtime') THEN
        CREATE TRIGGER update_sys_user_modtime BEFORE UPDATE ON sys_user FOR EACH ROW EXECUTE FUNCTION update_modified_column();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_stream_config_modtime') THEN
        CREATE TRIGGER update_stream_config_modtime BEFORE UPDATE ON stream_config FOR EACH ROW EXECUTE FUNCTION update_modified_column();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_operation_log_modtime') THEN
        CREATE TRIGGER update_operation_log_modtime BEFORE UPDATE ON operation_log FOR EACH ROW EXECUTE FUNCTION update_modified_column();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_detection_result_modtime') THEN
        CREATE TRIGGER update_detection_result_modtime BEFORE UPDATE ON detection_result FOR EACH ROW EXECUTE FUNCTION update_modified_column();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_detection_box_modtime') THEN
        CREATE TRIGGER update_detection_box_modtime BEFORE UPDATE ON detection_box FOR EACH ROW EXECUTE FUNCTION update_modified_column();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_system_config_modtime') THEN
        CREATE TRIGGER update_system_config_modtime BEFORE UPDATE ON system_config FOR EACH ROW EXECUTE FUNCTION update_modified_column();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_training_record_modtime') THEN
        CREATE TRIGGER update_training_record_modtime BEFORE UPDATE ON training_record FOR EACH ROW EXECUTE FUNCTION update_modified_column();
    END IF;
END $$;
