"""TripClipper — local-first media triage and rough-cut planning tool.

M0 defines only the project skeleton, the data contract and the safety
boundary. Business logic (scanning, model analysis, export, Eagle, FastAPI)
is delivered by later modules.
"""

__version__ = "0.1.0"

# Schema version of the on-disk ``cut_index.json`` data contract.
SCHEMA_VERSION = "0.2"

__all__ = ["__version__", "SCHEMA_VERSION"]
