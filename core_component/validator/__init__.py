import os
import traceback
from .spec_library import SpecLibrary
from .validator import Validator

# Load the component compiler specs library
spec_library = SpecLibrary()


def validate_component(component_name, definitions, context):
    try:
        definition = definitions[component_name]
        if "Type" not in definition:
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

        component_type = definition["Type"]
        spec = spec_library.get_spec(component_type)

        if spec is None:
            return {
                "ValidationErrors": [
                    {
                        "Component": component_name,
                        "Details": {"Key": component_name},
                        "Message": "Validation error - Unknown consumable '{}'".format(
                            component_type
                        ),
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

    spec_spec_library = SpecLibrary(
        spec_file_globs=[os.path.join(script_dir, "specs", "*.yaml")], meta_prefix="__"
    )
    errors: list = []
    specs = spec_library.get_specs()

    spec_spec = spec_spec_library.get_spec("Spec")

    for spec_name in sorted(specs):
        spec = specs[spec_name]

        validator = Validator(spec_name, spec, spec_spec, meta_prefix="__")
        errors += validator.validate()

    return errors
