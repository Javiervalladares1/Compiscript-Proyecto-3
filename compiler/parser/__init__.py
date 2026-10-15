"""Integracion con ANTLR: carga de los archivos generados y manejo de errores."""

from .error_listener import CollectingErrorListener, install_error_listeners

__all__ = ["CollectingErrorListener", "install_error_listeners"]
