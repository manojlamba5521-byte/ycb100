"""Benchmarks — thin harnesses that feed fixed datasets into the
Universal Cognitive OS.

Each harness is short and single-purpose.  It does NOT contain
reasoning logic — the reasoning all lives in the universal solver
and its organs.  The harness's job is:

    1. Load the dataset.
    2. Build an appropriate DomainAdapter-compatible perceiver that
       turns each task into a ProblemIR / IntentIR / ObjectiveIR.
    3. Feed tasks through `ChatGateway.handle(...)` one at a time.
    4. Aggregate metrics and write a report.

Why this shape: a benchmark is a user of IGM, not a part of its
cognitive core.  Keeping harnesses here prevents them from slowly
accreting reasoning primitives that should live in core/.
"""
