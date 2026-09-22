"""Pipeline stage metadata and constants.

Currently the pipeline exposes two concretely wired handlers (converting,
structuring); a broader ordered stage model (classify -> extract -> validate
-> render -> publish) is described in the AI_FLOW 2.0 docs.
"""

STAGE_CONVERTING = "converting"
STAGE_STRUCTURING = "structuring"