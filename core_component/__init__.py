from .compiler import compile_app_files
from .preprocessor import load_user_variables, render_component_defintitions
from .security_engine import assume_role
from .validator import validate_component, validate_specs
from .handler import handler as pipeline_compiler

__version__ = "0.0.8"

__all__ = [
    "pipeline_compiler",
    "compile_app_files",
    "load_user_variables",
    "render_component_defintitions",
    "assume_role",
    "validate_component",
    "validate_specs",
]
