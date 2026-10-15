"""Adapters that hand a preprocessed session to other analysis packages.

Not exporters: an exporter writes a file from metric results, these return in-memory objects
built from the preprocessed positions. Each imports its third-party package lazily, so Track2Data
itself does not depend on it.
"""
