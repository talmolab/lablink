"""Flask blueprints for the allocator service's HTTP routes.

Deliberately empty: do NOT import or re-export anything from the submodules
here.

`main.py` creates the Flask `app` and imports every blueprint in this
package at startup (`app.register_blueprint(...)`). A submodule that did
`from lablink_allocator_service.main import database` at module level would
create an import cycle (main imports the blueprint; the blueprint imports
main) and, worse, would bind `database` to whatever it was — usually
`None` — at import time. That binding would never see `init_database()`
run, and it would never see the ~250 places the test suite monkeypatches
`lablink_allocator_service.main.<global>` (database, cfg, scheduler_service,
etc.), since patching the attribute on the `main` module object does not
retroactively update a name some other module already imported.

Each view instead does `from lablink_allocator_service import main` as the
first statement in the view body, then reads process state off the module
object (`main.database`, `main.cfg`, ...) at request time. That import is
lazy (deferred until the view runs, by which point `main` is fully
initialized) and reads through the module rather than binding a stale
local name, so both the import cycle and the stale-binding problem
disappear, and tests can still patch `main.<attr>` and have every view see
the patched value. Request-scoped configuration (e.g. `LABLINK_PROVIDER`)
is read from `current_app.config` instead, since that already flows
through Flask's app context correctly.

Keeping this file empty enforces the pattern: an import here would be
executed once at `main.py`'s module-load time, before the lazy per-request
import machinery it documents even applies.
"""
