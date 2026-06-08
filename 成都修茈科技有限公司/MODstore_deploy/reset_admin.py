import bcrypt
h = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
from modstore_server.models import User, get_session_factory
sf = get_session_factory()
with sf() as session:
    u = session.query(User).filter(User.username == "admin").first()
    if u:
        u.password_hash = h
        session.commit()
        print(f"admin password reset to bcrypt, hash={h[:30]}...")
    else:
        print("admin user not found")
