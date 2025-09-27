from typing import Any
import re
import zipfile

import core_framework as util

import core_logging as log

from core_renderer import Jinja2Renderer

DEFINITION_FILE_PATTERN = r"components/[^/\\]+\.yaml$"
VARS_FILE_PATTERN = r"vars/[^/\\]+\.yaml$"


def render_component_defintitions(package_file_path: str, context: dict[str, Any]) -> dict[str, Any]:
    """
    Load the component definitions from the provided zip file and render them
    with Jinja2 using the provided context.

    :param zip_file_path: Path to the zip file containing the component definitions.
    :type zip_file_path: str
    :param context: The context to render the component definitions with.
    :type context: dict[str, Any]
    :returns: The rendered component definitions.
    :rtype: dict[str, Any]
    """
    log.debug("Running preprocessor.  Template rendering component definitions")

    # Render the definitions files
    renderer = Jinja2Renderer()

    definitions_pattern = re.compile(DEFINITION_FILE_PATTERN)
    definitions: dict = {}
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
    """
    Load default variables AND ALL variables sections that match the branch name.

    THIS IS A CHANGE.

    The old methodology attempted to find ONE section in the variables file that matched the branch name.
    A "best match" approach.

    This new method will load the default variables AND ALL variables sections that match the branch name.

    So, if your branch name is "dev" and the variables file contains::

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

    Then the resulting variables will be::

        { Lab: Default, Ptn: dev, Foo: quux, Item: 123, Ref: 456 }

    All sections are inspected and merged. SEQUENCING is important. The last section to set a value for a key wins.

    :param branch: The branch name to match variables for.
    :type branch: str
    :param variables: Dictionary of all loaded variables sections.
    :type variables: dict[str, Any]
    :returns: The merged variables for the specified branch.
    :rtype: dict[str, Any]
    """
    result_variables: dict = {}

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
    """
    Load apps ``platform/vars/*.yaml`` from a zip file.

    This function reads all variables files from the provided zip file,
    merges them, and selects the variables for the specified branch.

    The method will read all variables files and MERGE them. Any sections that have the same names
    will be MERGED. Indeed, if a later file/section updates a variable in a section, the later file will win.

    Once all VARS have been "MERGED", the vars for your specific branch (matched) will be selected as a result.

    For use on the context::

        SomeCfnProp: {{ vars.FooBar }}

    :param facts: The facts about the deployment containing the "Branch" code for the vars.
    :type facts: dict[str, Any]
    :param zip_file_path: Path to the zip file containing the variables files.
    :type zip_file_path: str
    :returns: The user variables loaded from the vars/* folder.
    :rtype: dict[str, Any]
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
