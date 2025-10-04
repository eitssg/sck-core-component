from typing import Any
import os
import traceback

import core_framework as util

from .spec_library import SpecLibrary, SpecType
from .validator import Validator

# Load the component compiler specs library
spec_library: SpecLibrary = SpecLibrary()


def validate_component(component_name: str, definition: dict[str, Any]) -> dict:
    try:

        if definition is None:
            return {
                "ValidationErrors": [
                    {
                        "Component": component_name,
                        "Details": {"Key": component_name},
                        "Message": "Validation error - Missing component definition",
                    }
                ],
                "ValidationWarnings": [],
            }

        component_type = definition.get("Type")
        if component_type is None:
            return {
                "ValidationErrors": [
                    {
                        "Component": component_name,
                        "Details": {"Key": component_name},
                        "Message": "Validation error - Missing 'Type' property, could not determine component consumable",
                    }
                ],
                "ValidationWarnings": [],
            }

        spec = spec_library.get_spec(component_type)
        if spec is None:
            return {
                "ValidationErrors": [
                    {
                        "Component": component_name,
                        "Details": {"Key": component_name},
                        "Message": "Validation error - Unknown consumable '{}'".format(component_type),
                    }
                ],
                "ValidationWarnings": [],
            }

        # Validate the component
        validator = Validator(component_name, definition, spec)
        errors, warnings = validator.validate()

        return {"ValidationErrors": errors, "ValidationWarnings": warnings}

    except Exception as e:
        return {
            "ValidationErrors": [
                {
                    "Key": component_name,
                    "Message": "Internal error - {}".format(e),
                    "StackTrace": traceback.format_exc(),
                }
            ],
            "ValidationWarnings": [],
        }


def validate_specs() -> list:

    # Get the current folder of this script
    script_dir = os.path.dirname(os.path.realpath(__file__))

    paths = [
        os.path.join(script_dir, "specs", "*.yaml"),
        os.path.join(script_dir, "specs", "*.yml"),
        os.path.join(script_dir, "specs", "*.yaml.j2"),
    ]

    spec_spec_library = SpecLibrary(spec_file_globs=paths, meta_prefix="__")
    errors: list = []
    specs: dict[str, dict[str, Any]] = spec_library.get_specs()

    spec_spec: dict[str, Any] | None = spec_spec_library.get_spec("Spec")

    if spec_spec is None:
        errors.append(
            {
                "Key": "Spec",
                "Message": "Internal error - Could not find 'Spec' specification in the specs library",
            }
        )
        return errors

    for spec_name, definition in specs.items():
        validator = Validator(spec_name, definition, spec_spec, meta_prefix="__")
        errors += validator.validate()

    return errors
