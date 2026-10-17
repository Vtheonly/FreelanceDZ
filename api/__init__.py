"""FastAPI application package.

Importing this package first verifies that the installed framework stack is
coherent (issue #3): pip can leave a superficially installed environment
whose Starlette is too new for the installed FastAPI (or unsatisfying for a
co-installed Streamlit). The guard must run before ``api.server`` imports
construct any ``APIRouter`` — that is why it lives at package scope, ahead
of the server import. In a healthy environment the check costs ~1 ms; in a
broken one the developer gets an actionable error instead of
``TypeError: Router.__init__() got an unexpected keyword argument
'on_startup'`` deep inside Starlette.
"""

from core.dependency_guard import verify_runtime_dependencies

verify_runtime_dependencies()

from api.server import app, create_app  # noqa: E402

__all__ = ["app", "create_app"]
