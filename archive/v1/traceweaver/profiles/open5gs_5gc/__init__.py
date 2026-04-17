from traceweaver.core.profile.registry import register_profile
from traceweaver.profiles.open5gs_5gc.profile import Open5GS5GCProfile

register_profile(Open5GS5GCProfile())

__all__ = ["Open5GS5GCProfile"]
