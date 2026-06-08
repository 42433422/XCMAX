# -*- coding: utf-8 -*-
"""
XCAGI 性能压力测试脚本 (Locust)

用于验证优化效果，模拟真实用户行为：
- 产品查询（读密集）
- AI对话（计算密集）
- 订单操作（写密集）
- 缓存命中率监控
- 响应时间统计

使用方法：
    # 安装 Locust
    pip install locust

    # 运行压力测试
    locust -f locustfile.py --host=http://localhost:5000

    # 无头模式运行
    locust -f locustfile.py --headless --users=100 --spawn-rate=10 --run-time=5m

    # 生成HTML报告
    locust -f locustfile.py --headless --users=50 --run-time=3m --html report.html
"""

import random
import string
from locust import HttpUser, task, between, events
from locust.runners import MasterRunner


class XCAGIUser(HttpUser):
    """
    XCAGI 模拟用户

    模拟真实用户行为模式：
    - 70% 读操作（查询产品、客户）
    - 20% 写操作（创建订单、更新数据）
    - 10% AI对话（智能交互）
    """

    wait_time = between(1, 5)  # 用户思考时间1-5秒

    def on_start(self):
        """用户登录/初始化"""
        self.user_id = f"test_user_{self.user_id}"
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @task(30)
    def get_products_list(self):
        """获取产品列表（最频繁的操作）"""
        params = {
            "page": random.randint(1, 10),
            "per_page": random.choice([10, 20, 50]),
            "keyword": random.choice(["", "油漆", "涂料", "树脂"]),
        }
        with self.client.get(
            "/api/products",
            params=params,
            headers=self.headers,
            name="/api/products [列表]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    response.success()

                    # 验证缓存标记
                    if data.get("_cached"):
                        self.environment.events.request.fire(
                            request_type="CACHE",
                            name="产品列表缓存命中",
                            response_time=0,
                            response_length=0,
                            context={"cached": True},
                        )
                else:
                    response.failure(f"业务错误: {data.get('message')}")
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(15)
    def get_product_detail(self):
        """获取产品详情"""
        product_id = random.randint(1, 100)
        with self.client.get(
            f"/api/products/{product_id}",
            headers=self.headers,
            name="/api/products/:id [详情]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if not data.get("success") and data.get("message") != "产品不存在":
                    response.failure(data.get("message", "未知错误"))
                else:
                    response.success()
            elif response.status_code == 404:
                response.success()  # 404是正常的（可能不存在的产品ID）
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(10)
    def search_products(self):
        """搜索产品"""
        keywords = ["油漆", "环氧", "聚氨酯", "防腐", "工业", "水性"]
        keyword = random.choice(keywords)

        with self.client.get(
            "/api/products",
            params={"keyword": keyword},
            headers=self.headers,
            name=f"/api/products?keyword={keyword} [搜索]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(5)
    def ai_chat_simple(self):
        """AI简单对话"""
        messages = [
            "查询所有油漆类产品",
            "今天有什么优惠活动？",
            "帮我推荐一款防腐涂料",
            "查看我的订单状态",
            "最近有哪些新产品？",
        ]
        message = random.choice(messages)

        payload = {
            "user_id": self.user_id,
            "message": message,
            "source": "locust_test",
        }

        with self.client.post(
            "/api/ai/chat",
            json=payload,
            headers=self.headers,
            name="/api/ai/chat [简单对话]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if data.get("text"):
                    response.success()

                    # 检查是否命中缓存
                    if data.get("_cached"):
                        self.environment.events.request.fire(
                            request_type="CACHE",
                            name="AI响应缓存命中",
                            response_time=response.elapsed.total_seconds(),
                            response_length=len(response.content),
                        )
                else:
                    response.failure("无返回文本")
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(3)
    def ai_chat_complex(self):
        """AI复杂对话（较长消息）"""
        payload = {
            "user_id": self.user_id,
            "message": (
                f"我需要为{'化工' if random.random() > 0.5 else '建筑'}项目"
                f"采购一批{'环氧' if random.random() > 0.5 else '聚氨酯'}"
                f"材料，预算在{random.randint(10000, 100000)}元左右，"
                f"要求具有{'耐高温' if random.random() > 0.5 else '防腐蚀'}性能，"
                f"请为我推荐合适的产品并生成报价单。"
            ),
            "context": {"project_type": "询价"},
            "source": "locust_test",
        }

        with self.client.post(
            "/api/ai/chat",
            json=payload,
            headers=self.headers,
            name="/api/ai/chat [复杂对话]",
            catch_response=True,
        ) as response:
            if response.elapsed.total_seconds() > 5.0:
                response.failure(f"响应过慢: {response.elapsed.total_seconds():.2f}s")
            elif response.status_code == 200:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(2)
    def create_shipment_order(self):
        """创建出货单（写操作）"""
        payload = {
            "customer_name": f"测试客户_{random.randint(1, 100)}",
            "items": [
                {
                    "product_id": random.randint(1, 50),
                    "quantity": random.randint(1, 100),
                    "unit_price": round(random.uniform(100, 1000), 2),
                }
                ],
            "delivery_address": f"测试地址_{random.randint(1, 100)}",
            "remark": "Locust压力测试",
        }

        with self.client.post(
            "/api/shipments",
            json=payload,
            headers=self.headers,
            name="/api/shipments [创建]",
            catch_response=True,
        ) as response:
            if response.status_code in [200, 201]:
                response.success()
            elif response.status_code == 429:
                response.success()  # 限流是正常的
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(5)
    def get_performance_status(self):
        """获取性能状态（监控端点）"""
        with self.client.get(
            "/api/performance/status",
            headers=self.headers,
            name="/api/performance/status [监控]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    components = data.get("data", {}).get("components", {})

                    # 记录缓存命中率
                    cache_stats = components.get("redis_cache", {})
                    hit_rate = cache_stats.get("stats", {}).get("hit_rate", 0)

                    if hit_rate > 0:
                        self.environment.events.request.fire(
                            request_type="METRIC",
                            name="缓存命中率",
                            response_time=hit_rate,
                            response_length=0,
                            context={"hit_rate_percent": hit_rate},
                        )

                    response.success()
                else:
                    response.failure("状态异常")
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(3)
    def health_check(self):
        """健康检查"""
        with self.client.get(
            "/api/performance/health",
            headers=self.headers,
            name="/api/performance/health [健康检查]",
            catch_response=True,
        ) as response:
            if response.status_code in [200, 503]:  # 503也是可接受的
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """
    测试结束时输出摘要报告
    """
    print("\n" + "=" * 70)
    print("📊 XCAGI 性能压力测试完成")
    print("=" * 70)

    stats = environment.stats

    total_requests = stats.total.num_requests
    total_failures = stats.total.num_failures
    failure_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0

    print(f"\n总请求数: {total_requests}")
    print(f"失败请求: {total_failures}")
    print(f"失败率: {failure_rate:.2f}%")

    print("\n🔝 慢接口 TOP 10:")
    sorted_stats = sorted(stats.entries.values(), key=lambda x: x.avg_response_time, reverse=True)[:10]

    for i, stat in enumerate(sorted_stats, 1):
        print(
            f"  {i:2d}. {stat.name:45s} "
            f"平均:{stat.avg_response_time:7.2f}ms  "
            f"P95:{stat.get_response_time_percentile(95):7.2f}ms  "
            f"RPS:{stat.current_rps:6.1f}"
        )

    print("\n✅ 测试完成！详细报告已生成。")


if __name__ == "__main__":
    import sys

    if "--help" in sys.argv or "-h" in sys.argv:
        print("""
XCAGI 性能压力测试工具

使用方法:

1. 启动 Web UI (推荐):
   locust -f locustfile.py --host=http://localhost:5000
   然后打开 http://8089

2. 命令行模式:
   locust -f locustfile.py --headless \\
       --host=http://localhost:5000 \\
       --users=100 \\
       --spawn-rate=10 \\
       --run-time=5m

3. 生成 HTML 报告:
   locust -f locustfile.py --headless \\
       --users=50 \\
       --run-time=3m \\
       --html performance_report.html

测试场景:
- 产品列表查询 (30%)
- 产品详情获取 (15%)
- 产品搜索 (10%)
- AI简单对话 (5%)
- AI复杂对话 (3%)
- 创建出货单 (2%)
- 性能状态监控 (5%)
- 健康检查 (3%)

指标关注点:
- 平均响应时间 < 200ms (优化后目标)
- P95延迟 < 800ms
- 错误率 < 1%
- 缓存命中率 > 80%
""")
    else:
        print("使用 'locust -f locustfile.py' 运行压力测试")
        print("或使用 '--help' 查看帮助信息")
