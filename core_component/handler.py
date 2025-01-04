"""Description: Compile a deployspec package into actions and templates.

# Extracts package files to a location in S3
# Parses and compiles the package deployspec (deployspec.yml)
# Uploads actions to S3
"""

from typing import Any
import os
import io
import re
import jmespath
import traceback
import zipfile as zip
import json
from datetime import datetime

import core_logging as log

import core_framework as util
from core_framework.status import COMPILE_COMPLETE, COMPILE_FAILED, COMPILE_IN_PROGRESS
from core_framework.constants import TR_RESPONSE, CTX_CONTEXT
from core_framework.models import TaskPayload, PackageDetails
from core_helper.magic import MagicS3Client

from core_db.dbhelper import register_item, update_status, update_item
from core_db.facter import get_facts

from .preprocessor import load_user_variables, render_component_defintitions
from .compiler import (
    combine_result_files,
    compile_app_files,
    render_component,
    assemble_context
)
from .validator import validate_component


def handler(event: dict, context: dict | None) -> dict:
    """AWS Lambda handler function.

    Must return with Task Response { "Response": "..." }

    Returns:
        dict: Task Response { "Response": "..." }
    """

    task_payload = TaskPayload(**event)

    # Update config (global)
    # os.environ["OUTPUT_PATH"] = package.get("OutputPath", "")
    # os.environ["PLATFORM_PATH"] = package.get("PlatformPath", "")

    # Setup logging (global)
    log.setup(task_payload.Identity)

    result = execute(task_payload)

    return {TR_RESPONSE: result}


class CompileException(Exception):
    """Exception raised when compilation fails."""

    def __init__(
        self,
        message,
        failed_components,
        successful_components,
        validation_errors,
        validation_warnings,
    ):
        super().__init__(message)
        self.message = message
        self.failed_components = failed_components
        self.successful_components = successful_components
        self.validation_errors = validation_errors
        self.validation_warnings = validation_warnings


def execute(task_payload: TaskPayload) -> dict:
    """Execute the compilation process. for pipelines.  Applcation template compiler."""
    try:
        log.info("Starting component compilation")

        deployment_details = task_payload.DeploymentDetails

        # Register branch and build with the API
        if not deployment_details.Branch or not deployment_details.Build:
            return {
                "Status": "error",
                "Message": "Branch and Build details are required",
            }

        branch_prn = deployment_details.get_branch_prn()
        build_prn = deployment_details.get_build_prn()

        register_item(branch_prn, deployment_details.Branch)
        register_item(build_prn, deployment_details.Build, status=COMPILE_IN_PROGRESS)

        facts = get_facts(deployment_details)

        update_status(
            build_prn,
            COMPILE_IN_PROGRESS,
            "Build compilation started at {}".format(datetime.now().isoformat()),
        )

        # Load all files into memory from package.zip.  How much memory will this take?
        files = __download_package(task_payload.Package)

        # Create the context for the jinja2 template engine with the facts and add in the user branch variables from files
        context = __create_context(task_payload, facts, files)

        # Will return with component definitions fully rendered
        # From the preprocessor module
        definitions = render_component_defintitions(files, context)

        # Register the components into the Database that will are defined in this deployment
        __register_components(task_payload, definitions, context)

        # Compile the components.  Raises an excepton on any failure.
        result = __compile_components(task_payload, definitions, context)

        return result

    except CompileException as e:
        try:
            update_status(build_prn, COMPILE_FAILED, str(e.message))
        except Exception:
            pass
        return __return(
            "Compilation failed",
            e.message,
            e.failed_components,
            e.successful_components,
            e.validation_errors,
            e.validation_warnings,
        )

    except Exception as e:
        try:
            update_status(build_prn, COMPILE_FAILED, str(e))
        except Exception:
            pass
        log.error(
            "Compilation failed",
            details={"Error": str(e), "StackTrace": traceback.format_exc()},
        )
        return {
            "Status": "error",
            "Message": "Compilation failed",
            "Error": {"Message": str(e), "StackTrace": traceback.format_exc()},
        }


def __create_context(
    task_payload: TaskPayload, facts: dict[str, Any], files: dict[str, Any]
) -> dict:
    """
    TODO - Move this!  This function is in the wrong module.  Or eliminate it altogether.  It is not needed.

    The idea is to read from the package.zip file the "platform/vars/*.yaml" files
    and add them to the jinja context.  It will build a context with the following

    {
        "context": {facts data from the deployment details},
        "vars": {vars data from the vars files in package.zip}
    }

    Args:
        task_payload (TaskPayload): The task payload object
        facts (dict): The facts dictionary
        files (dict): The files dictionary

    Returns:
        dict: The jija2 context dictionary

    """

    # Render the component definition files
    try:

        log.debug("Processing component definition files")

        # We will preporocess variable files with the current context
        # From the "preprocessor module"
        variables = load_user_variables(facts, files)

        context = assemble_context(facts, variables)

        return context

    except Exception as e:

        build_prn = task_payload.DeploymentDetails.get_build_prn()

        update_status(
            build_prn, COMPILE_FAILED, "Error processing component definition files"
        )

        exception_message = str(e)
        exception_message = re.sub(r" +", r" ", exception_message)
        exception_message = re.sub(r"\n([^ ])", r", \1", exception_message)
        exception_message = exception_message.replace("\n", "").replace('"', "'")

        log.error(
            "Build compilation failed - {}".format(exception_message),
            details={"StackTrace": traceback.format_exc()},
        )

        raise Exception(exception_message)


def __register_components(task_payload: TaskPayload, definitions: dict, context: dict):

    log.info("Registering components with the Database")
    log.debug("Registering components with the Database", details=definitions)

    deployment_details = task_payload.DeploymentDetails
    build_prn = deployment_details.get_build_prn()

    # Dump context as metadata in DynamoDB
    update_item(prn=build_prn, context=json.dumps(context))

    # Register components with the API
    for component_name, definition in definitions.items():
        if not isinstance(definition, dict):
            continue

        component_prn = "{}:{}".format(build_prn, component_name)
        image_alias, image_id = __get_component_image(
            definition, context[CTX_CONTEXT]["ImageAliases"]
        )

        log.debug("Registering component with the database:", details=definition)

        if image_alias:
            log.debug(
                "For component '{}', found image_alias '{}', image_id '{}'.".format(
                    component_name, image_alias, image_id
                )
            )

        register_item(
            component_prn,
            component_name,
            component_type=definition.get("Type", "N/A"),
            image_alias=image_alias,
            image_id=image_id,
        )


def __compile_components(
    task_payload: TaskPayload, definitions: dict, context: dict
) -> dict:

    log.info("Compiling components")

    deployment_details = task_payload.DeploymentDetails
    build_prn = deployment_details.get_build_prn()

    # Validate the components
    validation_results = __validate_definitions(build_prn, definitions, context)

    # Collect together all the validation errors and warnings
    validation_errors = []
    validation_warnings = []
    for result in validation_results.values():
        validation_errors.extend(result["ValidationErrors"])
        validation_warnings.extend(result["ValidationWarnings"])

    # Fail compilation if validation is enforced and there are any validation errors
    if util.is_enforce_validation() and validation_errors:
        update_status(
            build_prn,
            COMPILE_FAILED,
            "One or more components have failed validation",
        )

        return __return(
            status="error",
            message="One or more components have failed validation",
            validation_errors=validation_errors,
            validation_warnings=validation_warnings,
        )

    # Compile the components
    compile_results = __compile_component_definitions(
        build_prn=build_prn,
        definitions=definitions,
        context=context,
    )
    failed_components = {
        k: v for k, v in compile_results.items() if v["Status"] == "error"
    }
    successful_components = {
        k: v for k, v in compile_results.items() if v["Status"] == "ok"
    }

    log.debug("Updating build status")

    # Handle compliation failures
    if failed_components:

        log.error("One or more components have failed compilation")

        update_status(
            build_prn,
            COMPILE_FAILED,
            "One or more components have failed compilation",
        )

        return __return(
            "error",
            "One or more components have failed compilation",
            failed_components,
            successful_components,
            validation_errors,
            validation_warnings,
        )

    # Upload compiled files
    try:

        log.info("Uploading compiled components")

        # Combine files from each compiled component
        compiled_files = combine_result_files(compile_results)

        # Upload files
        __upload_compiled_files(task_payload, compiled_files)

    except Exception as e:
        log.error(
            "Error while uploading compiled components", details={"Error": str(e)}
        )

        update_status(build_prn, COMPILE_FAILED)

        return __return(
            "error",
            f"Error while uploading compiled components: {e}",
            failed_components,
            successful_components,
            validation_errors,
            validation_warnings,
        )

    # Complete
    message = "Compilation complete"

    if validation_errors:
        message += ", with {} validation errors".format(len(validation_errors))
    elif validation_warnings:
        message += ", with {} validation warnings".format(len(validation_warnings))

    log.info(message)

    return __return(
        "ok",
        message,
        failed_components,
        successful_components,
        validation_errors,
        validation_warnings,
    )


def __return(
    status,
    message,
    failed_components={},
    successful_components={},
    validation_errors=[],
    validation_warnings=[],
) -> dict:
    errors = validation_errors + [
        {"Component": k, "Details": v["Details"], "Message": v["Message"]}
        for k, v in failed_components.items()
    ]
    errors = sorted(errors, key=lambda k: k["Component"])
    warnings = sorted(validation_warnings, key=lambda k: k["Component"])

    return {
        "Status": status,
        "Message": message,
        "Components": successful_components,
        "CompilationErrors": errors,
        "CompilationWarnings": warnings,
    }


def __download_package(package: PackageDetails) -> dict[str, Any]:
    """
    Download the package.zip from S3 or local source and extract the files.
    and put into a dictionary indexed by the filename.

    Args:
        package (PackageDetails): package containing locaton of package.zip

    Returns:
        dict[str, Any]: List of all files read from the package.zip
    """

    bucket_name = package.BucketName
    bucket_region = package.BucketRegion
    version_id = package.VersionId

    if package.Key is None:
        raise ValueError("Package key is required")

    # Download package from S3
    log.info("Processing deployment package")
    log.debug(
        "Downloading object",
        details={
            "BucketName": bucket_name,
            "Key": package.Key,
            "VersionId": version_id,
        },
    )

    bucket = MagicS3Client.get_bucket(Region=bucket_region, BucketName=bucket_name)

    extra_args = {}
    if package.VersionId is not None:
        extra_args["VersionId"] = version_id
    fileobj = io.BytesIO()

    # Download the package from the S3 Bucket or MagicBucket
    bucket.download_fileobj(Key=package.Key, Fileobj=fileobj, ExtraArgs=extra_args)

    # The key should have been "package.zip"
    zipfile = zip.ZipFile(fileobj, "r")
    namelist = zipfile.namelist()

    files = {}
    for name in namelist:
        file_data = zipfile.read(name)
        files[name] = file_data.decode("utf-8")

    return files


def __upload_compiled_files(task_payload: TaskPayload, files: dict) -> dict:
    """
    Upload files to storage

    Args:
        task_payload (TaskPayload): the task_payload object
        files (dict): files to upload

    Returns:
        dict: returns a list of files with their upload results
    """

    deployment_details = task_payload.DeploymentDetails

    s3_artefacts_prefix = deployment_details.get_artefacts_key()
    s3_build_files_prefix = deployment_details.get_files_key()

    # Split user files and component files (uploaded to different locations)
    user_files = {}
    component_files = {}

    # The structure of the project platform folder is
    #
    # platform/
    # ├── components/
    # │   ├── component_definition.yaml
    # ├── files/
    # │   ├── file1.yaml
    # │   ├── file2.yaml
    # ├── vars/
    # │   ├── branch-prod.yaml
    # │   ├── branch-nonprod.yaml
    # │   ├── branch-dev.yaml
    #
    # The package.zip is an archive containing all platform folder contents compnents, files and vars folders.

    package = task_payload.Package
    bucket_name = package.BucketName
    bucket_region = package.BucketRegion

    bucket = MagicS3Client.get_bucket(Region=bucket_region, BucketName=bucket_name)

    # Get the bucket
    sep = "/" if util.is_use_s3() else os.path.sep

    result: dict = {}
    # Upload component files to storage
    for file_name, body in files.items():
        if file_name.startswith("files/"):
            user_files[file_name] = body
            result = __upload_object(
                bucket, bucket_region, s3_build_files_prefix, file_name, body, sep
            )

        elif file_name.startswith("components/") or file_name.startswith("vars/"):
            component_files[file_name] = body
            result = __upload_object(
                bucket, bucket_region, s3_artefacts_prefix, file_name, body, sep
            )

        else:
            log.warn("Unknown file type", details={"FileName": file_name})
            continue

        result[file_name] = result

    return result


def __get_component_image(
    definition: dict, image_aliases: dict
) -> tuple[str | None, str | None]:
    """
    Certain components have definition.Configuration.*.Properties.ImageId.Fn::Pipeline::ImageId.Name defined.
    Example: Autoscale|Cluster=BakeInstance|LaunchConfiguration, Instance
    FIXME AWS::LoadBalancedInstances components can have multiple "Instance" resources, with unique ImageIds!

    Args:
        definition (dict): The definition of the component
        image_aliases (dict): A dictionary of image aliases

    Returns:
        tuple: A tuple containing the image alias and image id

    """
    expression = jmespath.compile('Properties.ImageId."Fn::Pipeline::ImageId".Name')

    configuration = definition.get("Configuration")
    if isinstance(configuration, dict):

        # Search for the image alias in the resources.  Don't worrry abou the resource name,
        # we are only interested in the image alias.
        for _, resource in configuration.items():
            image_alias = expression.search(resource)
            if image_alias is None:
                continue
            image_id = image_aliases.get(image_alias, None)
            return image_alias, image_id

    return None, None


def __validate_definitions(build_prn: str, definitions: dict, context: dict) -> dict:
    """
    Validate component definitionss

    Args:
        build_prn (str): _description_
        definitions (dict): _description_
        context (dict): _description_
        environment (str): _description_

    Returns:
        dict: results of the validation.
    """

    log.info("Validating component definitions")

    results: dict = {}

    any_errors = False
    for component_name in sorted(definitions):

        component_prn = "{}:{}".format(build_prn, component_name)
        definition = definitions[component_name]

        # Validate the component
        update_status(
            component_prn, COMPILE_IN_PROGRESS, "Validating component definition"
        )

        result = validate_component(component_name, definitions, context)

        results[component_name] = result
        errors = result["ValidationErrors"]
        warnings = result["ValidationWarnings"]

        if errors:
            any_errors = True
            message = "Component '{}' has failed validation".format(component_name)
            log.error(
                message,
                details={
                    "Component": component_name,
                    "ValidationErrors": errors,
                    "ValidationWarnings": warnings,
                },
            )
        elif warnings:
            message = "Component '{}' has one or more validation warnings".format(
                component_name
            )
            log.warn(
                message,
                details={"ValidationErrors": errors, "ValidationWarnings": warnings},
            )

        # Update the component status
        if errors:
            if util.is_enforce_validation():
                # Validation errors with enforcement
                update_status(
                    component_prn,
                    COMPILE_FAILED,
                    "Component has failed validation",
                    details={"Consumable": definition["Type"]},
                )
            else:
                # Validation errors without enforcement
                update_status(
                    component_prn,
                    COMPILE_IN_PROGRESS,
                    "Component has failed validation, but validation is not being enforced",
                )
        elif warnings:
            # No errors but does have warnings
            update_status(
                component_prn,
                COMPILE_IN_PROGRESS,
                "Component validation completed with warnings",
            )
        else:
            # No warnings or errors
            update_status(
                component_prn, COMPILE_IN_PROGRESS, "Component validation completed"
            )

    # Cancel remaining compilations if validation is enforced and there are any validation errors
    if util.is_enforce_validation() and any_errors:

        for component_name in sorted(results):
            definition = definitions[component_name]

            result = results[component_name]
            component_prn = "{}:{}".format(build_prn, component_name)

            # Only update the status if we wouldn't have previously set status to COMPILE_FAILED
            if not result["ValidationErrors"]:
                update_status(
                    component_prn,
                    COMPILE_FAILED,
                    "Cancelled due to other build errors",
                    details={"Consumable": definition["Type"]},
                )

    return results


def __compile_component_definitions(
    build_prn: str,
    definitions: dict,
    context: dict,
) -> dict:
    """Pass each component throught the renderer for var replacement with the context."""

    results: dict = {}

    results["_application"] = compile_app_files(definitions, context)

    for component_name in sorted(definitions):
        definition = definitions[component_name]
        component_prn = "{}:{}".format(build_prn, component_name)

        result = render_component(component_name, definitions, context)

        if result["Status"] == "ok":
            # Successful compilation
            update_status(
                component_prn,
                COMPILE_COMPLETE,
                details={"Consumable": definition["Type"]},
            )
        else:
            # Errors during compilation
            update_status(
                component_prn,
                COMPILE_FAILED,
                message=result["Message"],
                details={"Consumable": definition["Type"]},
            )

        results[component_name] = result

    return results


def __upload_object(
    bucket: Any,
    bucket_region: str,
    prefix: str,
    file_name: str,
    body: Any,
    sep: str = "/",
) -> dict:
    """
    Save the object to the targed Bucket.

    For "Local" mode, the bucket is a MagicBucket object.  So, look on your filesystem

    prefix is the path to the object.  It will be a path like files/**, pacakges/**, artefacts/**

    files is a dictionary of binary objets (byte arrays) indexed by the filename.

    Args:
        bucket (Any): S3 Bucket or MagicBucket object
        bucket_region (str): Region for the S3 bucket
        prefix (str): prefix for the object.  Will be a path like files/**, pacakges/**, artefacts/**
        file_name (str): filename of the object
        body (Any): binary object (byte array)
        sep (str): path separator

    Returns:
        dict: _description_
    """

    key = "{}{}{}".format(prefix, sep, file_name)

    log.debug(
        "Uploading file to storage",
        details={
            "BucketName": bucket.name,
            "BucketRegion": bucket_region,
            "Key": key,
        },
    )

    object = bucket.put_object(
        Body=body,
        Key=key,
        ServerSideEncryption="AES256",
        ACL="bucket-owner-full-control",
    )

    return {
        "BucketName": bucket.name,
        "BucketRegion": bucket_region,
        "Key": key,
        "VersionId": object.version_id,
    }
