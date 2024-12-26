import pytest
import json

from core_component_compiler import validate_specs


@pytest.fixture
def specifications():

    return {}


def test_validate_specs(specifications):

    assert specifications == {}

    errors = validate_specs()

    print(json.dumps(errors, indent=4, sort_keys=True))

    assert len(errors) == 0
