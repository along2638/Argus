-- PostgreSQL Database Initialization Script
-- Run this script to create the required tables and indexes

-- Create alarm_records table
CREATE TABLE IF NOT EXISTS alarm_records (
    id BIGSERIAL PRIMARY KEY,
    stream_url TEXT NOT NULL,
    stream_id VARCHAR(64),
    alarm_type VARCHAR(32) NOT NULL,    -- helmet/intrusion/fire/smoke
    confidence FLOAT4 NOT NULL,
    image_path TEXT NOT NULL,            -- MinIO object key
    track_id INTEGER,
    detected_by TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- BRIN index for time-series range queries
CREATE INDEX IF NOT EXISTS idx_alarm_detected_brin ON alarm_records USING brin(detected_by);

-- B-tree index for stream_id queries
CREATE INDEX IF NOT EXISTS idx_alarm_stream_id ON alarm_records(stream_id);

-- B-tree index for alarm_type queries
CREATE INDEX IF NOT EXISTS idx_alarm_type ON alarm_records(alarm_type);

-- Add comments
COMMENT ON TABLE alarm_records IS 'Alarm records from YOLO detection';
COMMENT ON COLUMN alarm_records.alarm_type IS 'Type of alarm: helmet, no-helmet, intrusion, fire, smoke';
COMMENT ON COLUMN alarm_records.image_path IS 'MinIO object key for the alarm image';
COMMENT ON COLUMN alarm_records.track_id IS 'Object tracking ID from ByteTrack';
