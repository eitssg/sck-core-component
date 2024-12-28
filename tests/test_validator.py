import pytest
import os
import json
from core_component.validator import SpecLibrary, Validator


spec_library = SpecLibrary()


def get_specs_to_validate() -> list:

    script_dir = os.path.realpath(
        os.path.sep.join(["core_component", "validator", "specs"])
    )

    spec_spec_library = SpecLibrary(
        spec_file_globs=[os.path.join(script_dir, "*.yaml")], meta_prefix="__"
    )
    specs = spec_library.get_specs()

    spec_spec = spec_spec_library.get_spec("Spec")

    data: list[tuple] = []
    for spec_name in sorted(specs):
        spec = specs[spec_name]
        data.append((spec_name, spec, spec_spec))
    return data


@pytest.mark.parametrize("spec_name,spec,spec_spec", get_specs_to_validate())
def test_validate_specs(spec_name, spec, spec_spec):

    validator = Validator(spec_name, spec, spec_spec, meta_prefix="__")

    errors, warnings = validator.validate()

    if warnings:
        pytest.xfail(json.dumps(warnings))

    assert errors == []
