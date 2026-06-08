# -*- coding: utf-8 -*-
"""
数据库索引优化建议

分析数据库模型并提供索引优化建议。
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


def generate_index_recommendations() -> List[Dict[str, str]]:
    """
    生成索引优化建议
    
    Returns:
        索引建议列表
    """
    recommendations = []
    
    # 1. 发货记录表索引
    recommendations.append({
        "table": "shipment_records",
        "index_name": "idx_shipment_status",
        "columns": "status",
        "reason": "状态字段常用于过滤查询",
        "sql": "CREATE INDEX idx_shipment_status ON shipment_records(status);"
    })
    
    recommendations.append({
        "table": "shipment_records",
        "index_name": "idx_shipment_created_at",
        "columns": "created_at",
        "reason": "时间字段常用于排序和范围查询",
        "sql": "CREATE INDEX idx_shipment_created_at ON shipment_records(created_at);"
    })
    
    recommendations.append({
        "table": "shipment_records",
        "index_name": "idx_shipment_product",
        "columns": "product_name, model_number",
        "reason": "商品名称和型号常用于联合查询",
        "sql": "CREATE INDEX idx_shipment_product ON shipment_records(product_name, model_number);"
    })
    
    recommendations.append({
        "table": "shipment_records",
        "index_name": "idx_shipment_unit",
        "columns": "purchase_unit, unit_id",
        "reason": "采购单位常用于分组查询",
        "sql": "CREATE INDEX idx_shipment_unit ON shipment_records(purchase_unit, unit_id);"
    })
    
    # 2. 产品表索引
    recommendations.append({
        "table": "products",
        "index_name": "idx_products_model",
        "columns": "model_number",
        "reason": "型号字段常用于精确查询",
        "sql": "CREATE INDEX idx_products_model ON products(model_number);"
    })
    
    recommendations.append({
        "table": "products",
        "index_name": "idx_products_category",
        "columns": "category, is_active",
        "reason": "分类和状态常用于联合过滤",
        "sql": "CREATE INDEX idx_products_category ON products(category, is_active);"
    })
    
    recommendations.append({
        "table": "products",
        "index_name": "idx_products_name",
        "columns": "name",
        "reason": "商品名称常用于搜索",
        "sql": "CREATE INDEX idx_products_name ON products(name);"
    })
    
    # 3. 客户表索引
    recommendations.append({
        "table": "customers",
        "index_name": "idx_customers_contact",
        "columns": "contact_phone",
        "reason": "联系电话常用于查询",
        "sql": "CREATE INDEX idx_customers_contact ON customers(contact_phone);"
    })
    
    # 4. 订单表索引（如果存在）
    recommendations.append({
        "table": "orders",
        "index_name": "idx_orders_customer",
        "columns": "customer_id, status",
        "reason": "客户 ID 和状态常用于联合查询",
        "sql": "CREATE INDEX idx_orders_customer ON orders(customer_id, status);"
    })
    
    recommendations.append({
        "table": "orders",
        "index_name": "idx_orders_created",
        "columns": "created_at",
        "reason": "创建时间常用于排序",
        "sql": "CREATE INDEX idx_orders_created ON orders(created_at);"
    })
    
    # 5. 库存表索引（如果存在）
    recommendations.append({
        "table": "inventory",
        "index_name": "idx_inventory_product",
        "columns": "product_id, warehouse_id",
        "reason": "产品和仓库常用于联合查询",
        "sql": "CREATE INDEX idx_inventory_product ON inventory(product_id, warehouse_id);"
    })
    
    return recommendations


def generate_composite_index_recommendations() -> List[Dict[str, str]]:
    """
    生成复合索引建议
    
    Returns:
        复合索引建议列表
    """
    recommendations = []
    
    # 常见查询模式分析
    recommendations.append({
        "table": "shipment_records",
        "index_name": "idx_shipment_query_optimization",
        "columns": "status, created_at DESC",
        "reason": "优化按状态过滤 + 时间排序的查询",
        "sql": "CREATE INDEX idx_shipment_query_optimization ON shipment_records(status, created_at DESC);",
        "query_pattern": "SELECT * FROM shipment_records WHERE status = ? ORDER BY created_at DESC"
    })
    
    recommendations.append({
        "table": "products",
        "index_name": "idx_products_active_search",
        "columns": "is_active, category, name",
        "reason": "优化活跃商品按分类搜索",
        "sql": "CREATE INDEX idx_products_active_search ON products(is_active, category, name);",
        "query_pattern": "SELECT * FROM products WHERE is_active = 1 AND category = ? ORDER BY name"
    })
    
    return recommendations


def check_existing_indexes(db_session) -> Set[str]:
    """
    检查已存在的索引
    
    Args:
        db_session: 数据库会话
        
    Returns:
        已存在的索引名称集合
    """
    existing_indexes = set()
    
    try:
        from sqlalchemy import inspect
        
        inspector = inspect(db_session.bind)
        tables = inspector.get_table_names()
        
        for table_name in tables:
            for index in inspector.get_indexes(table_name):
                existing_indexes.add(index['name'])
        
        logger.info(f"检测到 {len(existing_indexes)} 个现有索引")
        
    except Exception as e:
        logger.error(f"检查索引失败：{e}")
    
    return existing_indexes


def generate_migration_script(output_path: str = "migrations/add_indexes.sql"):
    """
    生成索引迁移脚本
    
    Args:
        output_path: 输出文件路径
    """
    recommendations = generate_index_recommendations()
    composite_recommendations = generate_composite_index_recommendations()
    
    all_recommendations = recommendations + composite_recommendations
    
    migration_sql = []
    migration_sql.append("-- 数据库索引优化迁移脚本")
    migration_sql.append(f"-- 生成日期：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    migration_sql.append("-- 索引总数：{}".format(len(all_recommendations)))
    migration_sql.append("")
    migration_sql.append("BEGIN TRANSACTION;")
    migration_sql.append("")
    
    for i, rec in enumerate(all_recommendations, 1):
        migration_sql.append(f"-- {i}. {rec['table']}.{rec['index_name']}")
        migration_sql.append(f"-- 原因：{rec['reason']}")
        if 'query_pattern' in rec:
            migration_sql.append(f"-- 查询模式：{rec['query_pattern']}")
        migration_sql.append(rec['sql'])
        migration_sql.append("")
    
    migration_sql.append("")
    migration_sql.append("COMMIT;")
    
    # 写入文件
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(migration_sql), encoding="utf-8")
    
    logger.info(f"✅ 索引迁移脚本已生成：{output_path}")
    
    return output_path


def analyze_table_indexes(table_name: str, db_session) -> Dict[str, Any]:
    """
    分析特定表的索引使用情况
    
    Args:
        table_name: 表名
        db_session: 数据库会话
        
    Returns:
        索引分析报告
    """
    try:
        from sqlalchemy import inspect, text
        
        inspector = inspect(db_session.bind)
        
        # 获取表的所有索引
        indexes = inspector.get_indexes(table_name)
        
        # 获取表列信息
        columns = inspector.get_columns(table_name)
        
        # 分析索引覆盖度
        indexed_columns = set()
        for index in indexes:
            for col in index.get('column_names', []):
                indexed_columns.add(col)
        
        all_columns = {col['name'] for col in columns}
        non_indexed_columns = all_columns - indexed_columns
        
        return {
            "table_name": table_name,
            "total_indexes": len(indexes),
            "indexed_columns": list(indexed_columns),
            "non_indexed_columns": list(non_indexed_columns),
            "coverage": len(indexed_columns) / len(all_columns) if all_columns else 0,
            "indexes": indexes,
        }
        
    except Exception as e:
        logger.error(f"分析表 {table_name} 索引失败：{e}")
        return {
            "table_name": table_name,
            "error": str(e),
        }


if __name__ == "__main__":
    import time
    
    # 生成索引建议
    recommendations = generate_index_recommendations()
    
    print("=" * 80)
    print("数据库索引优化建议")
    print("=" * 80)
    print(f"总建议数：{len(recommendations)}")
    print()
    
    for i, rec in enumerate(recommendations, 1):
        print(f"{i}. {rec['table']}.{rec['index_name']}")
        print(f"   列：{rec['columns']}")
        print(f"   原因：{rec['reason']}")
        print(f"   SQL: {rec['sql']}")
        print()
    
    print("=" * 80)
    print("生成迁移脚本...")
    
    # 生成迁移脚本
    migration_path = generate_migration_script()
    print(f"迁移脚本已保存至：{migration_path}")
    
    print("=" * 80)
