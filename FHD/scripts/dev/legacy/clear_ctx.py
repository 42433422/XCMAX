# mypy: disable-error-code="attr-defined"
import sys

sys.path.insert(0, r"E:\FHD\XCAGI")
from app.db.models import WechatContactContext
from app.db.session import get_db

with get_db() as db:
    ctx = db.query(WechatContactContext).filter(WechatContactContext.contact_id == 1).first()
    if ctx:
        print("Deleting context for contact_id=1")
        db.delete(ctx)
        db.commit()
        print("Deleted successfully")
    else:
        print("No context found for contact_id=1")
