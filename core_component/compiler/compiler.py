"""Component compilation helpers (template + action rendering layer).

Provides low-level rendering primitives used by the higher-level
``core_component.handler`` orchestration.

Responsibilities:
        * Render application-scoped templates (``events`` and ``kms``) via :func:`compile_app_files`.
        * Render individual component consumables (actions, files, userfiles) via :func:`render_component`.
        * Merge artefact/action outputs for upload (:func:`combine_result_files`).
        * Generate hierarchical PRNs (Portfolio / App / Branch / Build / Component).

Result Envelope
---------------
Compilation helpers that perform rendering return a dictionary with the shape::

        {
            "Status": "ok" | "error",
            "Message": str,
            "Details": dict,          # Populated with StackTrace on error
            "Actions": {str: str},     # Action name -> rendered content
            "Files": {str: str}        # Relative path -> rendered file content
        }

Notes:
        * Exceptions are swallowed and transformed into ``Status="error"`` envelopes
            (stack trace in ``Details.StackTrace``) so callers have uniform handling.
        * Action key collisions concatenate content (``+=``); File key collisions use
            last-writer-wins semantics when flattened.
        * Internal helpers prefixed ``__`` are implementation details but documented
            for Sphinx technical reference.
"""

from typing import Any, Dict
import os
import traceback

import core_framework as util
from core_framework.constants import CTX_COMPONENT_NAME, CTX_CONTEXT, CTX_APP, CTX_COMPONENT

import core_logging as log

from core_renderer import Jinja2Renderer

from ..validator import ComponentDefintionList, ComponentDefintion


# Create the actions renderer.  Templaes are stored relative to this file
application_path = os.path.join(os.path.dirname(__file__), "application")
application_renderer = Jinja2Renderer(application_path)

# Create the consumables renderer.  Templates are stored relative to this file
consumables_path = os.path.join(os.path.dirname(__file__), "consumables")
consumable_renderer = Jinja2Renderer(consumables_path)


def compile_app_files(definitions: ComponentDefintionList, context: Dict[str, Any]) -> Dict[str, Any]:
    """Compile application-scoped (non-component) actions and files.

    Renders predefined application sections (``events`` and ``kms``) into the
    standard result envelope. Outputs are namespaced under the ``_application/``
    directory for files.

    Args:
        definitions (dict): Full component definitions mapping (exposed for context if templates reference it).
        context (dict): Canonical rendering context containing deployment facts under ``CTX_CONTEXT``.

    Returns:
        dict: Standard result envelope (see module docstring).

    Notes:
        Exceptions are caught and converted to an ``error`` envelope; stack trace
        available at ``Details.StackTrace``.
    """
    # Construct the render context

    prns = __generate_prns(context)

    sep = "/" if util.is_use_s3() else os.path.sep

    application_url_prefix = sep.join(
        [
            context[CTX_CONTEXT]["ArtefactsBucketUrl"],
            context[CTX_CONTEXT]["ArtefactsPrefix"],
            "_application",
        ]
    )

    # PRN's and the app defintions are not added to the "context",
    # You can use them for the purpose of generating actions files and
    # cloudformation templates.
    render_context = util.deep_merge(
        context,
        {
            CTX_CONTEXT: {
                **prns,
                "ApplicationUrlPrefix": application_url_prefix,
            },
            CTX_APP: definitions,
        },
    )

    # TODO - fixme.  This is wrong.  The list of application files should come from the user package.
    # Should probably not be an empty list here.
    # Should be user defined "deploy.actions", "teardown.actions", "plan.actions", etc.
    application_actions: Dict[str, str] = {}

    application_files: Dict[str, str] = {}
    try:

        for section in ["events", "kms"]:
            actions_path = os.path.join(section, "actions")
            files_path = os.path.join(section, "files")

            # Render application actions.  Checkout all the files
            # in core_component/application/events/actions
            # and core_component/application/kms/actions
            # We render these with the context facts.  Remember the "CTX_CONTEXT" is "context"
            # in the pipeline compiler.
            action_files: Dict[str, str] = application_renderer.render_files(actions_path, render_context)
            application_actions = __combine_objects(application_actions, action_files)

            # Render application files.  Get the template files
            # in core_component/application/events/files
            # and core_component/application/kms/files
            # We render these with the context facts.  Remember the "CTX_CONTEXT" is "context"
            # in the pipeline compiler.
            files_files: Dict[str, str] = application_renderer.render_files(files_path, render_context)

            # TODO - Fixme: I don't like the _application subfolder.  it's not needed.
            files_files = {f"_application/{k}": v for k, v in files_files.items()}

            application_files = __combine_objects(application_files, files_files)

        # By now we have all the application actions and application files

        return {
            "Status": "ok",
            "Message": "App files compilation successful",
            "Details": {},
            "Actions": application_actions,
            "Files": application_files,
        }

    except Exception as e:
        return {
            "Status": "error",
            "Message": str(e),
            "Details": {"StackTrace": traceback.format_exc()},
        }


def render_component(component_name: str, definitions: ComponentDefintionList, context: Dict[str, Any]) -> Dict[str, Any]:
    """Render a single component's actions, files, and userfiles.

    Discovers the component template root by splitting its fully-qualified
    ``Type`` (``Provider::Service::Resource``) into a directory path and renders
    any present ``actions/``, ``files/`` and ``userfiles/`` subdirectories.

    Args:
        component_name (str): Logical component identifier.
        definitions (dict): Mapping of all component definitions (exposed as ``app`` context).
        context (dict): Base render context including facts + vars.

    Returns:
        dict: Standard result envelope.

    Notes:
        A failure in any stage returns an ``error`` envelope with stack trace.
    """
    # Extract current component definition
    definition: ComponentDefintion = definitions[component_name]

    # Generate PRNs
    prns = __generate_prns(context, component_name)

    sep = "/" if util.is_use_s3() else os.path.sep

    facts = context[CTX_CONTEXT]

    try:
        component_key_prefix = sep.join([facts["ArtefactsPrefix"], component_name])
        component_url_prefix = sep.join([facts["ArtefactsBucketUrl"], component_key_prefix])

        consumable = definition["Type"]
        if not consumable or "::" not in consumable:
            raise ValueError("Component Type is required and must be in 'Provider::Service::Resource' format")

        parts = consumable.split("::")
        if len(parts) < 2:
            raise ValueError(
                "Invalid component Type '{}'; must be in 'Provider::Service::Resource' format".format(definition["Type"])
            )
        provider = parts[0]

        aws_region = facts.get("AwsRegion")
        if not aws_region:
            raise ValueError("AwsRegion fact is required in context")

        environment = facts.get("Environment")
        if not environment:
            raise ValueError("Environment fact is required in context")

        aws_account = facts.get("AwsAccountId")
        if not aws_account:
            raise ValueError("AwsAccountId fact is required in context")

        # Construct the render context
        render_context = util.deep_merge(
            context,
            {
                CTX_CONTEXT: {
                    **prns,
                    "ComponentUrlPrefix": component_url_prefix,
                    "ComponentKeyPrefix": component_key_prefix,
                },
                CTX_COMPONENT_NAME: component_name,
                CTX_COMPONENT: {
                    "Name": component_name,
                    "Provider": provider,
                    "Consumable": consumable,
                    "Region": aws_region,
                    "Environment": environment,
                    "Account": aws_account,
                },
                CTX_APP: definitions,
            },
        )

        # Split component type by '::' to get the path of templates we need to render
        log.info(f"Compiling consumable {consumable}")

        base_path = os.path.join(*parts)
        actions_path = os.path.join(base_path, "actions")
        files_path = os.path.join(base_path, "files")
        userfiles_path = os.path.join(base_path, "userfiles")

        # Render actions
        component_actions: Dict[str, str] = consumable_renderer.render_files(actions_path, render_context)

        # Render files
        component_files: Dict[str, str] = consumable_renderer.render_files(files_path, render_context)
        component_files = {("{}/{}".format(component_name, k)): v for k, v in component_files.items()}

        # Render userfiles
        component_userfiles: Dict[str, str] = consumable_renderer.render_files(userfiles_path, render_context)
        component_userfiles = {("{}/userfiles/{}".format(component_name, k)): v for k, v in component_userfiles.items()}
        component_files.update(component_userfiles)

        result = {
            "Status": "ok",
            "Message": "Component compilation successful",
            "Details": {},
            "Actions": component_actions,
            "Files": component_files,
        }

    except Exception as e:
        result = {
            "Status": "error",
            "Message": str(e),
            "Details": {"StackTrace": traceback.format_exc()},
        }

    return result


def combine_result_files(results: dict[str, Any]) -> dict[str, str]:
    """Flatten multiple result envelopes into a single file mapping.

    Aggregates ``Actions`` (concatenating duplicate keys) and merges file
    content (last writer wins) across application + component results.

    Args:
        results (dict): Mapping of name -> result envelopes.

    Returns:
        dict: Merged file mapping (key -> content) suitable for upload.

    Notes:
        The order of concatenation for actions follows the iteration order of
        ``results.values()``.
    """
    files: dict[str, str] = {}
    for result in results.values():

        __combine_objects(files, result["Actions"])

        files.update(result["Files"])

    return files


def __combine_objects(object1: dict[str, str], object2: dict[str, str]) -> dict[str, str]:
    """Merge two action/file dictionaries, concatenating values on duplicate keys.

    Note that object 1 and object 2 are:

    object2 = { "<filename.txt>": "<contents of file... a string>" }

    What this is used for is that if the user defines their own "deploy", "release", "teardown"
    actions, then user defined acctions will be appended to the end of the actions filke that
    is defined in the complier library.

    Remember, we call a "list of actions" a "deployspec" and an "action" is an ActionResource object

    This method is also used to combine templates.  So if you have a User supplied resource tempalte
    that adds on to a Core component template (such as KMS resources for the cloud formation stack),
    then you could add to the default template.

    Example:

        >>> Compiler Library action list "deploy.actions"
        - Label: action1
          Kind: NoOp

        >>> User defined "deploy.actions"
        - Label: action2
          Kind: NoOp

        >>> Resulting final "deploy.actions"
        - Label: action1
          Kind: NoOp
        - Label: action2
          Kind: NoOp

    Args:
        object1 (Any): Existing aggregation target (expected ``dict[str, str]``).
        object2 (Any): Additional mapping to merge.

    Returns:
        Any: Mutated ``object1`` (for fluent aggregation) or original object if merge not applicable.

    Notes:
        Concatenation is naive string concatenation; upstream template content
        should already be structured to support this.
    """

    for key, value in object2.items():
        if key not in object1:
            # New key, create it
            object1[key] = value
        else:
            # Key exists, concatenate
            object1[key] += "\n"  # Ensure a newline between concatenated sections
            object1[key] += value

    return object1


def __generate_prns(context: dict, component_name: str | None = None) -> dict[str, str]:
    """Generate hierarchical PRNs (Portfolio → App → Branch → Build → Component).

    Args:
        context (dict): Rendering context containing deployment facts under ``CTX_CONTEXT``.
        component_name (str | None): Optional component to append a ``ComponentPrn``.

    Returns:
        dict: Mapping of PRN key names to their assembled string identifiers.
    """
    facts: dict[str, Any] = context[CTX_CONTEXT]

    # Construct the PRNs
    portfolio_prn = "prn:{}".format(facts.get("Portfolio", ""))
    app_prn = "{}:{}".format(portfolio_prn, facts.get("App", ""))
    branch_prn = "{}:{}".format(app_prn, facts.get("BranchShortName", ""))
    build_prn = "{}:{}".format(branch_prn, facts.get("Build", ""))

    # Construct the render context
    prns = {
        "PortfolioPrn": portfolio_prn,
        "AppPrn": app_prn,
        "BranchPrn": branch_prn,
        "BuildPrn": build_prn,
    }

    if component_name is not None:
        prns["ComponentPrn"] = "{}:{}".format(build_prn, component_name)

    return prns
