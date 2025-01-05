from typing import Any
import os
import traceback

import core_framework as util
from core_framework.constants import CTX_CONTEXT, CTX_VARS, CTX_APP

import core_logging as log

from core_renderer import Jinja2Renderer

# Create the renderers
application_path = os.path.join(os.path.dirname(__file__), "application")
application_renderer = Jinja2Renderer(application_path)

consumables_path = os.path.join(os.path.dirname(__file__), "consumables")
consumable_renderer = Jinja2Renderer(consumables_path)


def compile_app_files(definitions: dict, context: dict) -> dict:
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

    render_context = util.deep_merge(
        context,
        {
            CTX_CONTEXT: {
                **prns,
                "ApplicationUrlPrefix": application_url_prefix,
            },
            "app": definitions,
        },
    )

    application_actions: dict = {}
    application_files: dict = {}

    try:
        for section in ["events", "kms"]:
            actions_path = os.path.join(section, "actions")
            files_path = os.path.join(section, "files")

            # Render application actions.  Checkout all the files
            # in core_component/application/events/actions
            # and core_component/application/kms/actions
            # We render these with the context facts.  Remeber the "CTX_CONTEXT" is "context"
            # in the pipeline compiler.
            action_files = application_renderer.render_files(
                actions_path, render_context
            )
            application_actions = __combine_objects(application_actions, action_files)

            # Render application files.  Get the template files
            # in core_component/application/events/files
            # and core_component/application/kms/files
            # We render these with the context facts.  Remeber the "CTX_CONTEXT" is "context"
            # in the pipeline compiler.
            files_files = application_renderer.render_files(files_path, render_context)
            files_files = {f"_application/{k}": v for k, v in files_files.items()}
            application_files = __combine_objects(application_files, files_files)

        # By now we have all the application actions and application files

    except Exception as e:
        return {
            "Status": "error",
            "Message": str(e),
            "Details": {"StackTrace": traceback.format_exc()},
        }

    return {
        "Status": "ok",
        "Message": "App files compilation successful",
        "Details": {},
        "Actions": application_actions,
        "Files": application_files,
    }


def render_component(component_name: str, definitions: dict, context: dict) -> dict:

    # Extract current component definition
    definition = definitions[component_name]

    # Generate PRNs
    prns = __generate_prns(context, component_name)

    sep = "/" if util.is_use_s3() else os.path.sep

    facts = context[CTX_CONTEXT]

    try:
        component_url_prefix = sep.join([
            facts["ArtefactsBucketUrl"],
            facts["ArtefactsPrefix"],
            component_name,
        ])
        component_key_prefix = sep.join([facts["ArtefactsPrefix"], component_name])

        # Construct the render context
        render_context = util.deep_merge(
            context,
            {
                CTX_CONTEXT: {
                    **prns,
                    "ComponentUrlPrefix": component_url_prefix,
                    "ComponentKeyPrefix": component_key_prefix,
                },
                "component_name": component_name,
                "component": {
                    "Name": component_name,
                    "Provider": definition["Type"].split("::")[0],
                    "Consumable": definition["Type"],
                    "Region": facts["AwsRegion"],
                    "Environment": facts["Environment"],
                    "Account": facts["AwsAccountId"],
                },
                CTX_APP: definitions,
            },
        )

        # Split component type by '::' to get the path of templates we need to render
        log.info("Compiling consumable {}".format(definition["Type"]))

        base_path = os.path.join(*definition["Type"].split("::"))
        actions_path = os.path.join(base_path, "actions")
        files_path = os.path.join(base_path, "files")
        userfiles_path = os.path.join(base_path, "userfiles")

        # Render actions
        component_actions = consumable_renderer.render_files(
            actions_path, render_context
        )

        # Render files
        component_files = consumable_renderer.render_files(files_path, render_context)
        component_files = {
            ("{}/{}".format(component_name, k)): v for k, v in component_files.items()
        }

        # Render userfiles
        component_userfiles = consumable_renderer.render_files(
            userfiles_path, render_context
        )
        component_userfiles = {
            ("{}/userfiles/{}".format(component_name, k)): v
            for k, v in component_userfiles.items()
        }
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


def combine_result_files(results: dict) -> dict:

    files: dict = {}
    for result in results.values():

        __combine_objects(files, result["Actions"])

        files.update(result["Files"])

    return files


def __combine_objects(object1: Any, object2: Any) -> Any:

    if isinstance(object1, dict) and isinstance(object2, dict):
        for key, value in object2.items():
            if key not in object1:
                # New key, create it
                object1[key] = value
            else:
                # Key exists, concatenate
                object1[key] += value

    return object1


def __generate_prns(context: dict, component_name: str | None = None) -> dict:
    """
    Description: Generate the PRNs for the current context

    Args:
        context (dict): _description_
        component_name (str | None, optional): _description_. Defaults to None.

    Returns:
        dict: _description_
    """
    facts = context[CTX_CONTEXT]

    # Construct the PRNs
    portfolio_prn = "prn:{}".format(facts["Portfolio"])
    app_prn = "{}:{}".format(portfolio_prn, facts["App"])
    branch_prn = "{}:{}".format(app_prn, facts["BranchShortName"])
    build_prn = "{}:{}".format(branch_prn, facts["Build"])

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


def assemble_context(facts: dict[str, Any], vars: dict[str, Any]) -> dict:
    """
    Build the initial context with facts and vars

    Returns:
        dict: The jija2 context dictionary
    """

    context = {CTX_CONTEXT: facts, CTX_VARS: vars}

    return context
