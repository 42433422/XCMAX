// R22 architecture 域开源锚点实测：Spring Framework 任务集 B1-B3
// 输出单行 JSON（RESULT:<json>）
import org.springframework.beans.factory.BeanCreationException;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.*;

public class Tasks {
    interface GreeterPort { String greet(String who); }
    static class Business {
        private final GreeterPort port;
        Business(GreeterPort port) { this.port = port; }
        String run() { return port.greet("r22"); }
    }
    static class AdapterA implements GreeterPort { public String greet(String w) { return "A:" + w; } }
    static class AdapterB implements GreeterPort { public String greet(String w) { return "B:" + w; } }
    static class BrokenInit {
        BrokenInit() { throw new IllegalStateException("boom-init"); }
    }
    static class ConcurrentSafe {
        private final List<String> seen = new CopyOnWriteArrayList<>();
        String handle(String t) { seen.add(t); return "ok"; }
        int count() { return seen.size(); }
    }

    @Configuration
    static class CfgA {
        @Bean GreeterPort greeter() { return new AdapterA(); }
        @Bean Business business(GreeterPort p) { return new Business(p); }
        @Bean ConcurrentSafe concurrent() { return new ConcurrentSafe(); }
    }
    @Configuration
    static class CfgB {
        @Bean GreeterPort greeter() { return new AdapterB(); }
        @Bean Business business(GreeterPort p) { return new Business(p); }
        @Bean ConcurrentSafe concurrent() { return new ConcurrentSafe(); }
    }
    @Configuration
    static class CfgBroken {
        @Bean GreeterPort greeter() { return new AdapterA(); }
        @Bean Business business(GreeterPort p) { return new Business(p); }
        @Bean BrokenInit broken() { return new BrokenInit(); }
    }
    @Configuration
    static class BusinessOnly {
        @Bean Business business(GreeterPort p) { return new Business(p); } // 无端口实现 → fail-fast
    }

    static String j(String k, Object v) {
        return "\"" + k + "\":" + (v instanceof String ? "\"" + ((String) v).replace("\"", "'") + "\"" : String.valueOf(v));
    }

    public static void main(String[] args) throws Exception {
        StringBuilder sb = new StringBuilder("{\"benchmark\":\"spring\",\"version\":\"5.3.39\",\"tasks\":{");
        ConcurrentSafe cs = null;

        // B1 组合根+生命周期，替换适配器无需修改业务核心
        try {
            AnnotationConfigApplicationContext ctxA = new AnnotationConfigApplicationContext(CfgA.class);
            AnnotationConfigApplicationContext ctxB = new AnnotationConfigApplicationContext(CfgB.class);
            String a = ctxA.getBean(Business.class).run();
            String b = ctxB.getBean(Business.class).run();
            boolean swapped = a.equals("A:r22") && b.equals("B:r22");
            AnnotationConfigApplicationContext tmp = new AnnotationConfigApplicationContext(CfgB.class);
            cs = tmp.getBean(ConcurrentSafe.class);
            tmp.close();
            boolean lifecycle = false;
            try { tmp.getBean(Business.class); } catch (IllegalStateException e) { lifecycle = true; }
            ctxA.close(); ctxB.close();
            sb.append("\"B1\":{").append(j("verdict", swapped && lifecycle ? "PASS" : "FAIL"))
              .append(",").append(j("adapter_a", a)).append(",").append(j("adapter_b", b))
              .append(",").append(j("mechanism", "组合根 @Configuration；业务核心仅依赖端口接口，换适配器零改动；close 即释放生命周期")).append("},");
        } catch (Exception e) {
            sb.append("\"B1\":{").append(j("verdict", "FAIL")).append(",").append(j("error", e.toString())).append("},");
        }

        // B2 契约可自动验证（缺依赖启动即失败）
        try {
            AnnotationConfigApplicationContext bad = new AnnotationConfigApplicationContext();
            bad.register(BusinessOnly.class);
            boolean threw = false;
            try { bad.refresh(); } catch (Exception e) { threw = true; }
            try { bad.close(); } catch (Exception ignore) { }
            sb.append("\"B2\":{").append(j("verdict", threw ? "PASS" : "FAIL"))
              .append(",").append(j("mechanism", "容器启动即校验依赖契约：端口无实现时 refresh 抛异常（fail-fast）")).append("},");
        } catch (Exception e) {
            sb.append("\"B2\":{").append(j("verdict", "FAIL")).append(",").append(j("error", e.toString())).append("},");
        }

        // B3 初始化/并发可定位
        try {
            boolean initLocated = false; String cause = "";
            try {
                new AnnotationConfigApplicationContext(CfgBroken.class);
            } catch (BeanCreationException e) {
                initLocated = "broken".equals(e.getBeanName()) && String.valueOf(e.getRootCause()).contains("boom-init");
                cause = e.getBeanName() + "/" + e.getRootCause();
            }
            ExecutorService ex = Executors.newFixedThreadPool(4);
            final ConcurrentSafe fcs = cs;
            List<Future<?>> fs = new ArrayList<>();
            for (int i = 0; i < 40; i++) {
                int t = i;
                fs.add(ex.submit(() -> fcs.handle("t" + t)));
            }
            for (Future<?> f : fs) f.get(5, TimeUnit.SECONDS);
            ex.shutdown();
            boolean concurrentOk = cs.count() == 40;
            sb.append("\"B3\":{").append(j("verdict", initLocated && concurrentOk ? "PASS" : "FAIL"))
              .append(",").append(j("init_failure_located", cause))
              .append(",").append(j("concurrent_count", cs.count()))
              .append(",").append(j("mechanism", "BeanCreationException 定位 bean 名+根因；单例并发访问无丢失")).append("},");
        } catch (Exception e) {
            sb.append("\"B3\":{").append(j("verdict", "FAIL")).append(",").append(j("error", e.toString())).append("},");
        }
        sb.append("}}");
        String out = sb.toString().replace(",}}", "}}");
        System.out.println("RESULT:" + out);
    }
}
