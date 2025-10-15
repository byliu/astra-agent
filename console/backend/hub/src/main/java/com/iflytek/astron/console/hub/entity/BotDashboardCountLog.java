package com.iflytek.astron.console.hub.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDate;

/**
 * Bot Dashboard Count Log Entity Corresponds to bot_dashboard_count_log table
 *
 * @author Omuigix
 */
@Data
@TableName("bot_dashboard_count_log")
public class BotDashboardCountLog {

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /**
     * User UID
     */
    private Long uid;

    /**
     * Bot ID (stored as varchar in database)
     */
    private String botId;

    /**
     * Client channel
     */
    private Integer channel;

    /**
     * Chat session ID
     */
    private Long chatId;

    /**
     * Chat duration in seconds
     */
    private Integer chatTime;

    /**
     * Token consumed in this conversation
     */
    private Integer token;

    /**
     * Session identifier
     */
    private String sid;

    /**
     * Creation date
     */
    private LocalDate createTime;

    /**
     * Builder pattern for creating instances
     */
    public static Builder createBuilder() {
        return new Builder();
    }

    public static class Builder {
        private final BotDashboardCountLog instance = new BotDashboardCountLog();

        public Builder uid(String uid) {
            try {
                this.instance.uid = Long.parseLong(uid);
            } catch (NumberFormatException e) {
                this.instance.uid = null;
            }
            return this;
        }

        public Builder botId(Integer botId) {
            this.instance.botId = botId != null ? botId.toString() : null;
            return this;
        }

        public Builder channel(Integer channel) {
            this.instance.channel = channel;
            return this;
        }

        public Builder chatId(Long chatId) {
            this.instance.chatId = chatId;
            return this;
        }

        public Builder chatTime(Integer chatTime) {
            this.instance.chatTime = chatTime;
            return this;
        }

        public Builder token(Integer token) {
            this.instance.token = token;
            return this;
        }

        public Builder sid(String sid) {
            this.instance.sid = sid;
            return this;
        }

        public Builder createTime(LocalDate createTime) {
            this.instance.createTime = createTime;
            return this;
        }

        public BotDashboardCountLog build() {
            if (this.instance.createTime == null) {
                this.instance.createTime = LocalDate.now();
            }
            return this.instance;
        }
    }
}
