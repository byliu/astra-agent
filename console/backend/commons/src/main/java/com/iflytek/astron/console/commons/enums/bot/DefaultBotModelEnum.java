package com.iflytek.astron.console.commons.enums.bot;

/**
 * @author mingsuiyongheng Default model enum class
 */
public enum DefaultBotModelEnum {

    X1("星火大模型 Spark X1", "x1", "https://openres.xfyun.cn/xfyundoc/2025-09-24/e9b74fbb-c2d6-4f4a-8c07-0ea7f03ee03a/1758681839941/icon.png"),
    SPARK_4_0("星火大模型 Spark V4.0 Ultra", "spark", "https://openres.xfyun.cn/xfyundoc/2025-09-24/e9b74fbb-c2d6-4f4a-8c07-0ea7f03ee03a/1758681839941/icon.png"),
    DEEPSEEK_V3("DeepSeek-V3", "deepseek-chat", "https://openres.xfyun.cn/xfyundoc/2025-10-13/ccc37b07-5f50-419b-b92c-d1147b8a640a/1760345450309/%E5%BE%AE%E4%BF%A1%E5%9B%BE%E7%89%87_20251013165000_27.png"),
    DEEPSEEK_R1("DeepSeek-R1", "deepseek-reasoner", "https://openres.xfyun.cn/xfyundoc/2025-10-13/ccc37b07-5f50-419b-b92c-d1147b8a640a/1760345450309/%E5%BE%AE%E4%BF%A1%E5%9B%BE%E7%89%87_20251013165000_27.png");

    private String name;
    private String domain;
    private String icon;

    DefaultBotModelEnum(String name, String domain, String icon) {
        this.name = name;
        this.domain = domain;
        this.icon = icon;
    }

    public String getName() {
        return name;
    }

    public String getDomain() {
        return domain;
    }

    public String getIcon() {
        return icon;
    }

    /**
     * Get the corresponding enum constant by domain
     *
     * @param domain Model domain
     * @return Corresponding enum constant, returns null if not found
     */
    public static DefaultBotModelEnum getByDomain(String domain) {
        if (domain == null) {
            return null;
        }
        for (DefaultBotModelEnum model : DefaultBotModelEnum.values()) {
            if (domain.equals(model.getDomain())) {
                return model;
            }
        }
        return null;
    }
}
