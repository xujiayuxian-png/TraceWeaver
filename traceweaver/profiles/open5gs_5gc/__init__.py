"""
open5gs_5gc: the reference 5GC (Open5GS) diagnosis profile for TraceWeaver v2.

Package contents:
- `fields`  : canonical tshark field names this profile asks PcapSource
              to extract.
- `enrich`  : record enricher that derives `event`, cause names, and a
              protocol layer from the raw tshark columns.
- `tools/`  : five 5GC-specific tools exposed to the LLM.
- `knowledge/`: reference material (5GMM / 5GSM cause codes, procedure
              summaries) the LLM can search when it needs rationale.

The actual profile is declared in `profile.yaml` alongside this module;
`traceweaver analyze --profile open5gs_5gc` resolves here.
"""
