package com.modstore.util;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 与 Python {@code account_level_service.build_level_profile} 阈值一致，供 {@code /api/auth/me} 等返回展示字段。
 */
public final class LevelProfileBuilder {

    private record Threshold(int level, int minExp, String title) {}

    private static final Threshold[] ROWS = {
            new Threshold(1, 0, "新手"),
            new Threshold(2, 1_000, "探索者"),
            new Threshold(3, 5_000, "创作者"),
            new Threshold(4, 20_000, "专家"),
            new Threshold(5, 50_000, "大师"),
            new Threshold(6, 100_000, "宗师"),
            new Threshold(7, 200_000, "传奇"),
    };

    private LevelProfileBuilder() {}

    public static Map<String, Object> build(long experience) {
        long exp = Math.max(experience, 0);
        Threshold current = ROWS[0];
        Threshold next = ROWS.length > 1 ? ROWS[1] : null;

        for (int idx = 0; idx < ROWS.length; idx++) {
            Threshold row = ROWS[idx];
            if (exp >= row.minExp()) {
                current = row;
                next = idx + 1 < ROWS.length ? ROWS[idx + 1] : null;
            } else {
                break;
            }
        }

        int currentMin = current.minExp();
        Integer nextMin = next != null ? next.minExp() : null;
        double progress;
        if (nextMin == null) {
            progress = 1.0;
        } else {
            int span = Math.max(nextMin - currentMin, 1);
            progress = Math.max(0.0, Math.min(1.0, (exp - currentMin) / (double) span));
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("level", current.level());
        out.put("title", current.title());
        out.put("experience", exp);
        out.put("current_level_min_exp", currentMin);
        out.put("next_level_min_exp", nextMin);
        out.put("progress", Math.round(progress * 10_000) / 10_000.0);
        return out;
    }
}
