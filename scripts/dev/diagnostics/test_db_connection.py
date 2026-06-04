import sys
sys.path.insert(0, 'app')
from config import Config
from sqlalchemy import create_engine, text

engine = create_engine(Config.DATABASE_URL)
with engine.connect() as conn:
    # 检查 pgvector 扩展
    result = conn.execute(text("SELECT * FROM pg_extension WHERE extname = 'vector'"))
    extensions = result.fetchall()
    
    if extensions:
        print("✅ pgvector 扩展：已安装")
    else:
        print("❌ pgvector 扩展：未安装")
        print("   请运行：CREATE EXTENSION IF NOT EXISTS vector;")
    
    # 检查表是否存在
    result = conn.execute(text("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name LIKE 'alembic_version'
    """))
    tables = result.fetchall()
    
    if tables:
        print("✅ 数据库表结构：已初始化")
    else:
        print("⚠️  数据库表结构：可能未初始化")
        print("   请运行：python -m alembic upgrade head")
