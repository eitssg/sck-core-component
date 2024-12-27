import core_logging as log  # ignore untyped
import os
import core_framework as util
import traceback
from core_renderer import Jinja2Renderer

# Create the renderers
application_path = os.path.join(os.path.dirname(__file__), "application")
application_renderer = Jinja2Renderer(application_path)

consumables_path = os.path.join(os.path.dirname(__file__), "consumables")
consumable_renderer = Jinja2Renderer(consumables_path)


def compile_app_files(definitions, context):
    # Construct the render context
    prns = __generate_prns(context)
    application_url_prefix = "{}/{}/{}".format(
        context["context"]["ArtefactsBucketUrl"],
        context["context"]["ArtefactsPrefix"],
        "_application",
    )
    render_context = util.deep_merge(
        context,
        {
            "context": {
                **prns,
                "ApplicationUrlPrefix": application_url_prefix,
            },
            "app": definitions,
        },
    )

    application_actions = {}
    application_files = {}

    try:
        for section in ["events", "kms"]:
            actions_path = os.path.join(section, "actions")
            files_path = os.path.join(section, "files")

            # Render application actions
            files = application_renderer.render_files(actions_path, render_context)
            application_actions = __combine_objects(application_actions, files)

            # Render application files
            files = application_renderer.render_files(files_path, render_context)
            files = {("_application/{}".format(k)): v for k, v in files.items()}
            application_files = __combine_objects(application_files, files)

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


def render_component(component_name, definitions, context):
    # Extract current component definition
    definition = definitions[component_name]

    # Generate PRNs
    prns = __generate_prns(context, component_name)
    component_prn = prns["ComponentPrn"]

    log.set_identity(component_prn)

    try:
        component_url_prefix = "{}/{}/{}".format(
            context["context"]["ArtefactsBucketUrl"],
            context["context"]["ArtefactsPrefix"],
            component_name,
        )
        component_key_prefix = "{}/{}".format(
            context["context"]["ArtefactsPrefix"], component_name
        )

        # Construct the render context
        render_context = util.deep_merge(
            context,
            {
                "context": {
                    **prns,
                    "ComponentUrlPrefix": component_url_prefix,
                    "ComponentKeyPrefix": component_key_prefix,
                },
                "component_name": component_name,
                "component": {
                    "Name": component_name,
                    "Provider": definition["Type"].split("::")[0],
                    "Consumable": definition["Type"],
                    "Region": context["context"]["Region"],
                    "Environment": context["context"]["Environment"],
                    "Account": context["context"]["Account"],
                },
                "app": definitions,
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
    finally:
        log.reset_identity()

    return result


def combine_result_files(results):

    files = {}
    for name, result in results.items():
        __combine_objects(files, result["Actions"])
        files.update(result["Files"])

    return files


def __combine_objects(object1, object2):
    for key, value in object2.items():
        if key not in object1:
            # New key, create it
            object1[key] = value
        else:
            # Key exists, concatenate
            object1[key] += value

    return object1


def __generate_prns(context, component_name=None):
    # Construct the PRNs
    portfolio_prn = "prn:{}".format(context["context"]["Portfolio"])
    app_prn = "{}:{}".format(portfolio_prn, context["context"]["App"])
    branch_prn = "{}:{}".format(app_prn, context["context"]["BranchShortName"])
    build_prn = "{}:{}".format(branch_prn, context["context"]["Build"])

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
