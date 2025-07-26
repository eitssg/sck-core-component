from typing import Any
import re
import io

import core_framework as util

import core_logging as log

from core_renderer import Jinja2Renderer

DEFINITION_FILE_PATTERN = r"components/[^/\\]+\.yaml$"
VARS_FILE_PATTERN = r"vars/[^/\\]+\.yaml$"


def render_component_defintitions(
    files: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """
    Load the component definitions from the provided files and render them
    with Jinja2 using the provided context.

    Args:
        files (dict): A dictionary of filenames and their contents.
        context (dict): The context to render the component definitions with.

    Returns:
        dict: The rendered component definitions.
    """
    log.debug("Running preprocessor.  Template rendering component definitions")

    # Render the definitions files
    renderer = Jinja2Renderer(dictionary=files)

    definitions: dict = {}
    for filename in files:

        # Skip non-definition files
        if not re.match(DEFINITION_FILE_PATTERN, filename):
            continue

        # Render the file
        log.debug("Processing definition file '{}'".format(filename))
        rendered = renderer.render_file(filename, context)

        # YAML load and save the component definitions
        stream = io.StringIO(rendered)
        stream.name = filename
        file_definitions = util.read_yaml(stream)

        # If empty file - just ignore it
        if not file_definitions:
            continue

        # Add definitions in this file to other definitions
        if isinstance(file_definitions, dict):
            definitions.update(file_definitions)
        else:
            raise RuntimeError(
                "Invalid component definition file '{}'".format(filename)
            )

    return definitions


def __select_branch_variables(
    branch: str, variables: dict[str, Any]
) -> dict[str, Any]:  # noqa: C901
    """Load default variables AND ALL variables section that match the branch name.

    THIS IS A CHANGE.

    The old methdology attemted to find ONE section in the variables file that matched the branch name.
    A "best match" approach.

    This new method will load the default variables AND ALL variables sections that match the branch name.

    So, if your branch name is "dev" and the variables file contains:

    _defaults:
        Lab: Default
        Foo: bar

    dev:
        Ptn: dev
        Foo: baz

    de*:
        Foo: qux

    d*:
        Foo: quux
        Item: 123

    another:
        match: ^dev$
        Ref: 456

    Then the resulting variables will be:

    { Lab: Default, Ptn: dev, Foo: quux, Item: 123, Ref: 456 }

    All sections are inspected and merged. SEQUENCING is important.  The last section to set a value for a key wins.

    """

    result_variables: dict = {}

    for branch_pattern, branch_variables in variables.items():
        if not isinstance(branch_variables, dict):
            continue

        # Match by name
        if branch_pattern in ["_defaults", "_default", "defaults", "default", branch]:
            util.deep_merge_in_place(
                result_variables, branch_variables, merge_lists=True
            )
            continue

        # Match by wildcard
        if branch_pattern.endswith("*"):
            branch_prefix = branch_pattern.rstrip("*")
            if branch.startswith(branch_prefix):
                util.deep_merge_in_place(
                    result_variables, branch_variables, merge_lists=True
                )
                continue

        # Match by regex pattern
        regex = branch_variables.get("match", None)
        if regex and re.match(regex, branch):
            util.deep_merge_in_place(
                result_variables, branch_variables, merge_lists=True
            )
            continue

    return result_variables


def load_user_variables(facts: dict[str, Any], files: dict[str, Any]) -> dict[str, Any]:
    """
    Load apps ``platform/vars/*.yaml``,

    for use on the context:

    SomeCfnProp: {{ vars.FooBar }}

    CHANGE IN FUNCTIONALITY.

    The old method used to read each file in alphabetical order and sections would overwrite a previously read
    section.

    NEW METHOD

    The new method will read all variables files and MERGE them.  Any sections that thave the same names
    will be MERGED.  Indeed, if a later file/section updates a variable in a section, the later file will win.

    Once all VARS have bee "MERGED", the vars for your specific branch (matched) will be selected as a result.

    Args:
        facts (dict): The facts about the deployment containing the "Branch" code for the vars.
        files (dict): The files to load the variables from.

    Returns:
        dict: The user variables loaded from the vars/* folder.

    """
    # Load variables files
    variables: dict = {}

    branch = facts.get("Branch")
    if not branch:
        log.warning("No branch information found in facts")
        return variables

    log.info("Loading user variables for {} branch", branch)

    for filename in files:

        # Skip non-vars files
        if not re.match(VARS_FILE_PATTERN, filename):
            continue

        log.debug("Processing variables file '{}'".format(filename))
        stream = io.StringIO(files[filename])
        stream.name = filename
        file_variables = util.read_yaml(stream)
        util.deep_merge_in_place(variables, file_variables, merge_lists=True)

    # Load variables for this branch
    branch_variables = __select_branch_variables(branch, variables)

    log.debug("Branch '{}' variables included:", branch, details=branch_variables)

    return branch_variables
