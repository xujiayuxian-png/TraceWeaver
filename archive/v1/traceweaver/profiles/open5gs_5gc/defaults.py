DEFAULT_5GC_DISPLAY_FILTER = "ngap || nas-5gs || http2 || pfcp"
DEFAULT_5GC_DECODE_AS = ("tcp.port==7777,http2",)
PRIMARY_PROTOCOL_ORDER = ("nas_5gs", "ngap", "http2", "pfcp")
PROTOCOL_NAME_MAP = {"nas-5gs": "nas_5gs"}
