-- Database migration script for adding publish management fields to bot_config table
-- Author: AI Assistant
-- Date: 2025-10-16
-- Updated: 2025-10-24 - Corrected version management architecture
-- Description: Add publish_status, publish_data, and version fields to support bot publication and version management
--
-- Architecture Design:
--   - bot_id: External identifier (constant across versions, like workflow.group_id)
--   - id: Auto-increment internal identifier (changes per version, like workflow.id)
--   - version: Version identifier (v1.0, v2.0, -1=main)
--   - Multiple versions of same bot share the same bot_id but have different id and version values

-- Add publish management and version control columns
ALTER TABLE bot_config
ADD COLUMN version VARCHAR(32) NOT NULL DEFAULT '-1' COMMENT 'version identifier: v1.0, v2.0, -1=main development version',
ADD COLUMN publish_status SMALLINT NOT NULL DEFAULT 0 COMMENT 'publish status bitmask: 0=unpublished, 1=XINGCHEN, 4=KAIFANG, 16=AIUI',
ADD COLUMN publish_data JSON NULL COMMENT 'published configuration data snapshot';

-- Drop the unique constraint on bot_id to allow multiple versions
ALTER TABLE bot_config DROP INDEX bot_id;

-- Create unique constraint on bot_id + version combination (similar to workflow's group_id + version)
ALTER TABLE bot_config ADD UNIQUE KEY uniq_bot_id_version (bot_id, version);

-- Create index for publish status queries
CREATE INDEX idx_bot_publish ON bot_config(bot_id, publish_status);

-- Verify the changes
SHOW COLUMNS FROM bot_config LIKE '%publish%';
SHOW COLUMNS FROM bot_config LIKE 'version';
SHOW INDEX FROM bot_config WHERE Key_name = 'uniq_bot_id_version';
SHOW INDEX FROM bot_config WHERE Key_name = 'idx_bot_publish';

-- Note: All existing records will have version='-1' (main development version)
-- When creating version snapshots:
--   - Same bot_id is preserved (constant identifier)
--   - New id is auto-generated (auto-increment)
--   - New version value is specified (v1.0, v1.1, v2.0, etc.)
