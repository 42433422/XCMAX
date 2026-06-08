import sys
sys.path.insert(0, "/root/成都修茈科技有限公司/MODstore_deploy")
from modstore_server.models_user import UserLlmCredential
from modstore_server.db.base import get_session_factory
SessionFactory = get_session_factory()
with SessionFactory() as s:
    keys = s.query(UserLlmCredential).all()
    for k in keys:
        ak = str(k.api_key or "")
        print(f"user_id={k.user_id} provider={k.provider} has_key={bool(ak)} key_prefix={ak[:12]}... base_url={k.base_url}")
