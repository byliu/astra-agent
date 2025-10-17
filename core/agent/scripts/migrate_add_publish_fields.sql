-- Database migration script for adding publish management fields to bot_config table
-- Author: AI Assistant
-- Date: 2025-10-16
-- Description: Add publish_status, publish_data, and group_id fields to support bot publication management

-- Add publish management columns
ALTER TABLE bot_config
ADD COLUMN group_id VARCHAR(40) NULL COMMENT 'bot group id for version management',
ADD COLUMN publish_status SMALLINT NOT NULL DEFAULT 0 COMMENT 'publish status bitmask: 0=unpublished, 1=XINGCHEN, 4=KAIFANG, 16=AIUI',
ADD COLUMN publish_data JSON NULL COMMENT 'published configuration data snapshot';

-- Create index for publish queries
CREATE INDEX idx_group_publish ON bot_config(group_id, publish_status);

-- Verify the changes
SHOW COLUMNS FROM bot_config LIKE '%publish%';
SHOW COLUMNS FROM bot_config LIKE 'group_id';
SHOW INDEX FROM bot_config WHERE Key_name = 'idx_group_publish';

-- Optional: Update existing records to set default group_id (if needed)
-- UPDATE bot_config SET group_id = CONCAT('group_', id) WHERE group_id IS NULL;
