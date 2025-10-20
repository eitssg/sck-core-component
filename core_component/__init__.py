from .compiler import compile_app_files
from .preprocessor import load_user_variables, render_component_defintitions
from .validator import validate_component, validate_specs
from .handler import handler as pipeline_compiler

from importlib.metadata import version

__version__ = version("sck-core-component")

__all__ = [
    "pipeline_compiler",
    "compile_app_files",
    "load_user_variables",
    "render_component_defintitions",
    "validate_component",
    "validate_specs",
]
