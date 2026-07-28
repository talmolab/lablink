"""Database access layer for the allocator service.

Deliberately empty: do NOT re-export the classes from the submodules here.

Every submodule is imported directly (``from ...db.vms import VmDatabase``).
A module-level ``import psycopg2`` binds the module object at import time, so
whichever module performs pool construction is the one whose binding of
psycopg2 actually gets used. If this file re-exported the submodules,
importing *any one* of them — including the dependency-free ``db.pool`` —
would eagerly execute ``db/vms.py`` and its top-level ``import psycopg2`` as
a side effect. Keeping this file empty keeps ``import db.pool`` (or any other
submodule) from dragging in ``db.vms`` it has no need of.
"""
