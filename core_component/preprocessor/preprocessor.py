from typing import Any

import io
import core_logging as log
import re
from ruamel import yaml
import core_framework as util

from core_renderer import Jinja2Renderer

DEFINITION_FILE_PATTERN = r"components/[^/\\]+\.yaml$"
VARS_FILE_PATTERN = r"vars/[^/\\]+\.yaml$"


def load_user_variables(
    files: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Load apps ``platform/vars/*.yaml``, e.g::

        SomeCfnProp: {{ vars.FooBar }}

    Keyed off branch name, _defaults also supported.

    **Be careful** - these vars files are merged in alphabetical order, so the same keys in 2 vars files will clobber each others values.
    """

    # Load variables files
    variables: dict = {}
    for filename in files:

        # Skip non-vars files
        if not re.match(VARS_FILE_PATTERN, filename):
            continue

        log.debug("Processing variables file '{}'".format(filename))
        stream = io.StringIO(files[filename])
        stream.name = filename
        file_variables = yaml.YAML(typ="safe").load(stream)

        if file_variables is None:
            file_variables = {}

        variables = {**variables, **file_variables}

    # Load variables for this branch
    variables = __select_branch_variables(context["context"]["Branch"], variables)

    log.debug("User variables include: {}".format(list(variables.keys())))

    return variables


def run(files: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Load the component definitions from the provided files and render them
    with Jinja2 using the provided context.

    Args:
        files (dict): A dictionary of filenames and their contents.
        context (dict): The context to render the component definitions with.

    Returns:
        dict: The rendered component definitions.
    """
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
        file_definitions = yaml.YAML(typ="safe").load(stream)

        if file_definitions is None:
            # Empty file - just ignore it
            continue

        if isinstance(file_definitions, dict):
            # Add definitions in this file to other definitions
            definitions = {**definitions, **file_definitions}
        else:
            raise RuntimeError(
                "Invalid component definition file '{}'".format(filename)
            )

    return definitions


def __select_branch_variables(branch: str, variables: dict[str, Any]) -> dict[str, Any]:
    # Load defaults

    if "_defaults" in variables:
        log.debug("Loading default user variables")
        defaults = variables["_defaults"]
    else:
        log.debug("No default user variables (_defaults) were provided")
        defaults = {}

    current_matched_pattern = None
    current_specificity = -1

    for branch_pattern, branch_variables in variables.items():
        # Don't consider _default as a branch pattern
        if branch_pattern == "_defaults":
            continue

        if branch == branch_pattern:
            # Branch name matches exactly
            current_matched_pattern = branch_pattern
            current_specificity = len(branch_pattern)
            break

        elif branch_pattern.endswith("*"):
            # Pattern match the branch
            branch_prefix = branch_pattern.rstrip("*")

            # Bail out if we don't have a match
            if not branch.startswith(branch_prefix):
                continue

            # Bail out if we already have a more specific match
            specificity = len(branch_prefix)
            if specificity <= current_specificity:
                continue

            # This is the most specific match so far, save it
            current_matched_pattern = branch_pattern
            current_specificity = specificity

        else:
            # Not an exact match and not a pattern match
            continue

    if current_matched_pattern is not None:
        log.info(
            "Selecting variables pattern '{}' for branch '{}'".format(
                current_matched_pattern, branch
            )
        )
        return util.deep_merge(defaults, variables[current_matched_pattern])

    log.info("No variables pattern found for branch '{}'".format(branch))
    return defaults
