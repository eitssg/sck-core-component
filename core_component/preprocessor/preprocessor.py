"""Preprocess and render component definition & variable files.

This module performs two primary responsibilities prior to the main
compilation stage executed in ``core_component.handler`` / ``compiler``:

1. Component Definition Rendering:
     YAML files found under ``components/`` inside the deployment package
     (zip archive) are rendered through Jinja2 with a fully assembled
     context (facts + user variables). The merged result is a single
     dictionary mapping component name -> definition tree.

2. User Variable Resolution:
     All YAML files under ``vars/`` are loaded and *deep merged* (later files
     win). Each file may contain multiple branch-specific sections. A branch
     name (``facts['Branch']``) is matched using the following precedence and
     patterns (all matches are merged in order of appearance):

     * Section name equals one of ``_defaults``, ``_default``, ``defaults``, ``default``
     * Section name equals the branch exactly
     * Section name ends with ``*`` and the prefix matches the start of the branch
     * Section body contains a ``match`` key whose regex matches the branch

The final structure returned by :func:`load_user_variables` is the merged
set of variable key/value pairs AFTER applying the above logic.

Conventions & Behavior:
* Jinja2 rendering uses :class:`core_renderer.Jinja2Renderer`.
* YAML parsing uses ``util.from_yaml``; deep merges rely on
    ``util.deep_merge_in_place(..., merge_lists=True)``.
* Non‑matching files are ignored silently; invalid definition files raise
    ``RuntimeError``.
* Logging is structured via ``core_logging`` (imported as ``log``).

Examples:
        Rendering component definitions:

        >>> ctx = {"context": {"Branch": "dev"}, "vars": {"Foo": "Bar"}}
        >>> defs = render_component_defintitions("/tmp/package.zip", ctx)
        >>> isinstance(defs, dict)
        True

Note:
        The function name ``render_component_defintitions`` retains the
        historical misspelling for backward compatibility. Avoid renaming
        without coordinating consumers.
"""

from typing import Any
import re
import zipfile

import core_framework as util

import core_logging as log

from core_renderer import Jinja2Renderer

from ..validator import ComponentDefintionList

DEFINITION_FILE_PATTERN = r"components/[^/\\]+\.yaml$"
VARS_FILE_PATTERN = r"vars/[^/\\]+\.yaml$"


def render_component_defintitions(package_file_path: str, context: dict[str, Any]) -> ComponentDefintionList:
    """Render all component definition YAML files.

    Iterates over ``components/*.yaml`` entries in the deployment package
    (zip archive), renders each through Jinja2 with the supplied
    ``context`` and merges their resulting dictionaries into a single
    definitions map.

    Args:
        package_file_path (str): Absolute (or accessible) path to the
            deployment package zip archive.
        context (dict[str, Any]): Jinja2 rendering context combining facts
            and user variables (see :func:`load_user_variables`).

    Returns:
        dict[str, Any]: Mapping of component name -> component definition.

    Raises:
        RuntimeError: If a definition file does not parse to a ``dict``.

    Note:
        Files producing empty / falsy rendered output are skipped.
    """
    log.debug("Running preprocessor.  Template rendering component definitions")

    # Render the definitions files
    renderer = Jinja2Renderer()

    definitions_pattern = re.compile(DEFINITION_FILE_PATTERN)

    definitions: ComponentDefintionList = {}

    with zipfile.ZipFile(package_file_path, "r") as zip_file:
        for filename in zip_file.namelist():

            # Skip non-definition files
            if not definitions_pattern.match(filename):
                continue

            # Render the file
            log.debug("Processing definition file '{}'".format(filename))

            file_content = zip_file.read(filename).decode("utf-8")
            rendered = renderer.render_string(file_content, context)
            if not rendered:
                continue

            file_definitions = util.from_yaml(rendered)

            # Add definitions in this file to other definitions
            if isinstance(file_definitions, dict):
                definitions.update(file_definitions)
            else:
                raise RuntimeError("Invalid component definition file '{}'".format(filename))

    return definitions


def __select_branch_variables(branch: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: C901
    """Select and merge branch-specific variable sections.

    Merges variable sections that match the provided ``branch`` using the
    following precedence rules (order of appearance in ``variables`` wins):

    1. Sections named one of ``_defaults``, ``_default``, ``defaults``, ``default``
    2. Section whose name exactly matches ``branch``
    3. Section whose name ends with ``*`` and the prefix matches the start of ``branch``
    4. Section whose dictionary contains a regex key ``match`` that matches ``branch``

    All matching sections are deep merged (``merge_lists=True``) into a result
    dictionary. Later matches overwrite earlier keys.

    Example:
        Source structure::

            _defaults: {Lab: Default, Foo: bar}
            dev: {Ptn: dev, Foo: baz}
            de*: {Foo: qux}
            d*: {Foo: quux, Item: 123}
            another: {match: ^dev$, Ref: 456}

        For ``branch='dev'`` the merged output becomes::

            {Lab: Default, Ptn: dev, Foo: quux, Item: 123, Ref: 456}

    Args:
        branch (str): Current branch name used for matching.
        variables (dict[str, Any]): Parsed variables mapping where each key
            is a section name and each value is either a mapping or scalar.

    Returns:
        dict[str, Any]: Deep merged mapping of variable names -> values.
    """
    result_variables: dict[str, Any] = {}

    for branch_pattern, branch_variables in variables.items():
        if not isinstance(branch_variables, dict):
            continue

        # Match by name
        if branch_pattern in ["_defaults", "_default", "defaults", "default", branch]:
            util.deep_merge_in_place(result_variables, branch_variables, merge_lists=True)
            continue

        # Match by wildcard
        if branch_pattern.endswith("*"):
            branch_prefix = branch_pattern.rstrip("*")
            if branch.startswith(branch_prefix):
                util.deep_merge_in_place(result_variables, branch_variables, merge_lists=True)
                continue

        # Match by regex pattern
        regex = branch_variables.get("match", None)
        if regex and re.match(regex, branch):
            util.deep_merge_in_place(result_variables, branch_variables, merge_lists=True)
            continue

    return result_variables


def load_user_variables(facts: dict[str, Any], package_file_path: str) -> dict[str, Any]:
    """Load and merge user variable files for a branch.

    Collects every ``vars/*.yaml`` file inside the deployment package
    zip, parses and deep merges them (later files override earlier)
    producing a consolidated variable section map. The branch-specific
    subset is then selected via :func:`__select_branch_variables`.

    Example (template usage)::

        SomeCfnProp: {{ vars.FooBar }}

    Args:
        facts (dict[str, Any]): Deployment / build facts containing at
            minimum ``Branch``.
        package_file_path (str): Path to the package zip file.

    Returns:
        dict[str, Any]: Merged variable mapping filtered for the branch.

    Notes:
        If the ``Branch`` fact is missing an empty mapping is returned and
        a warning is logged.
    """
    branch = facts.get("Branch")
    if not branch:
        log.warning("No branch information found in facts")
        return {}

    log.info("Loading user variables for {} branch", branch)

    vars_pattern = re.compile(VARS_FILE_PATTERN)
    variables: dict = {}
    with zipfile.ZipFile(package_file_path, "r") as zip_file:

        for file_path in zip_file.namelist():

            # Skip non-vars files
            if not vars_pattern.match(file_path):
                continue

            log.debug("Processing variables file '{}'".format(file_path))

            file_content = zip_file.read(file_path).decode("utf-8")
            file_variables = util.from_yaml(file_content)

            util.deep_merge_in_place(variables, file_variables, merge_lists=True)

    # Load variables for this branch
    branch_variables = __select_branch_variables(branch, variables)

    log.debug("Branch '{}' variables included:", branch, details=branch_variables)

    return branch_variables
