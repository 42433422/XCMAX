"""已废弃。"""
import warnings
from app.infrastructure.gateways import tts as _gw
warnings.warn("tts_facade 已废弃", DeprecationWarning, stacklevel=2)
synthesize_to_data_uri = _gw.synthesize_to_data_uri
trigger_common_tts_warmup = _gw.trigger_common_tts_warmup
__all__ = list(_gw.__all__)
