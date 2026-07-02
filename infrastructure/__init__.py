"""Infrastructure package — concrete adapters for external resources.

Everything that touches the network, the filesystem, or external APIs
lives here. The ``services`` and ``api`` layers depend only on the
``core.interfaces`` abstractions; this package provides the implementations
that are wired in at startup by ``api.dependencies``.
"""
