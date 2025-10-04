"""Compile a deployspec package into actions and templates.

High-level workflow:

1. Extract package files to a (local or MagicS3 backed) staging location
2. Parse and compile the deployspec (``deployspec.yml``) and component definition files
3. Register portfolio/app/branch/build + component records in the database
4. Render and validate component templates (enforce validation when configured)
5. Upload compiled artefacts and user files to S3 (or local Magic bucket)

This module exposes a Lambda-style ``handler`` plus internal helper functions. All
helpers beginning with a double underscore are internal implementation details and
are documented for Sphinx technical reference generation (Google/Napoleon style).
"""

from copy import deepcopy
from typing import Any
import os
import re
import jmespath
import traceback
from datetime import datetime

import core_logging as log

import core_framework as util
from core_framework.status import COMPILE_COMPLETE, COMPILE_FAILED, COMPILE_IN_PROGRESS
from core_framework.constants import CTX_VARS, TR_RESPONSE, CTX_CONTEXT
from core_framework.models import DeploymentDetails, TaskPayload, PackageDetails
from core_helper.magic import MagicS3Client

from core_db.dbhelper import register_item, update_status, update_item
from core_db.facter import get_facts

from .preprocessor import load_user_variables, render_component_defintitions
from .compiler import (
    combine_result_files,
    compile_app_files,
    render_component,
)
from .validator import validate_component


def handler(event: dict, context: dict | None) -> dict:
    """Lambda-style entrypoint for component compilation.

    Validates the inbound ``event`` as a :class:`TaskPayload`, sets correlation / identity
    logging context, executes the compilation pipeline and returns a task response envelope.

    Args:
        event (dict): Raw Lambda event / invocation payload expected to conform to ``TaskPayload``.
        context (dict | None): Lambda context object (ignored in local mode / tests).

    Returns:
        dict: A dictionary shaped like ``{"Response": <result>}`` where ``<result>`` is the
        normalized compilation status produced by :func:`execute` / ``__return``.

    Raises:
        pydantic.ValidationError: If the incoming payload cannot be validated as ``TaskPayload``.
    """
    task_payload = TaskPayload.model_validate(event)
    log.set_correlation_id(task_payload.correlation_id)

    # Update config (global)
    # os.environ["OUTPUT_PATH"] = package.get("OutputPath", "")
    # os.environ["PLATFORM_PATH"] = package.get("PlatformPath", "")

    # Setup logging (global)
    log.setup(task_payload.identity)

    result = execute(task_payload)

    return {TR_RESPONSE: result}


class CompileException(Exception):
    """Raised to short‑circuit the compilation with structured component results.

    This exception allows early termination while preserving partial success data
    (successful components, failed components, validation artefacts) so the caller
    can return a consistent response envelope.

    Attributes:
        message (str): Human readable failure summary.
        failed_components (dict): Mapping of component name -> failure record.
        successful_components (dict): Mapping of component name -> success record.
        validation_errors (list): Aggregated validation error entries.
        validation_warnings (list): Aggregated validation warning entries.
    """

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
    """Execute the full compilation workflow.

    Steps:
        1. Register portfolio/app/branch/build records.
        2. Retrieve contextual facts (``get_facts``) for the deployment.
        3. Download the package archive.
        4. Build Jinja2 context (facts + user variables).
        5. Render component definition files and register component records.
        6. Validate definitions (optionally enforcing errors).
        7. Compile/render components and upload artefacts + user files.

    Args:
        task_payload (TaskPayload): Validated task payload.

    Returns:
        dict: Normalized compilation result (see :func:`__return`).

    Raises:
        CompileException: For controlled compilation failures with structured content.
    """
    try:
        log.info("Starting component compilation")

        deployment_details = task_payload.deployment_details  # Fixed: lowercase attribute

        # Register branch and build with the API
        if not deployment_details.branch or not deployment_details.build:  # Fixed: lowercase attributes
            return {
                "Status": "error",
                "Message": "Branch and Build details are required",
            }

        facts = get_facts(deployment_details)

        contact_email = facts.get("OrganizationEmail", "<unknown>")

        register_item("portfolio", deployment_details, contact_email=contact_email)
        register_item("app", deployment_details, contact_email=contact_email)
        register_item("branch", deployment_details)
        register_item("build", deployment_details)

        update_status(
            "build",
            deployment_details,
            status=COMPILE_IN_PROGRESS,
            message="Build compilation started at {}".format(datetime.now().isoformat()),
        )

        package_file_path = __download_package(task_payload.package)

        context = __create_context(task_payload, facts, package_file_path)

        definitions = render_component_defintitions(package_file_path, context)

        # Register the components into the Database that will are defined in this deployment
        __register_components(task_payload, definitions, context)

        # Compile the components.  Raises an exception on any failure.
        result = __compile_components(task_payload, definitions, context)

        return result

    except CompileException as e:
        try:
            update_status("build", deployment_details, status=COMPILE_FAILED, message=str(e.message))
        except Exception:
            pass
        return __return(
            "error",  # Fixed: added status parameter
            e.message,
            e.failed_components,
            e.successful_components,
            e.validation_errors,
            e.validation_warnings,
        )

    except Exception as e:
        try:
            update_status("build", deployment_details, status=COMPILE_FAILED, message=str(e))
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

    finally:
        # Clean up the temporary zip file
        if package_file_path and os.path.exists(package_file_path):
            try:
                os.unlink(package_file_path)
                log.debug(f"Cleaned up temporary file: {package_file_path}")
            except Exception as cleanup_error:
                log.warning(f"Failed to clean up temporary file: {cleanup_error}")


def __create_context(task_payload: TaskPayload, facts: dict[str, Any], package_file_path: str) -> dict:
    """Build the Jinja2 rendering context.

    Reads ``platform/vars/*.yaml`` files from the downloaded package archive, merges
    them with deployment *facts* to produce the structure:

    ``{"context": <facts>, "vars": <aggregated user variables>}``

    Args:
        task_payload (TaskPayload): The current task payload (for status updates on failure).
        facts (dict[str, Any]): Deployment/environment facts derived from ``DeploymentDetails``.
        package_file_path (str): Local filesystem path to the downloaded package archive.

    Returns:
        dict: Assembled context dictionary consumed by compilation & validation.

    Raises:
        Exception: If variable loading or context assembly fails.
    """
    # Render the component definition files
    try:
        log.debug("Processing component definition files")

        # We will preprocess variable files with the current context
        # From the "preprocessor module"
        variables = load_user_variables(facts, package_file_path)

        context = {CTX_CONTEXT: facts, CTX_VARS: variables}

        return context

    except Exception as e:
        deployment_details = task_payload.deployment_details  # Fixed: lowercase attribute

        update_status("build", deployment_details, status=COMPILE_FAILED, message="Error processing component definition files")

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
    """Register each component definition.

    Updates the build record metadata with full context, then iterates through all
    component definitions extracting image alias / id information (if present) and
    persists component records via ``register_item``.

    Args:
        task_payload (TaskPayload): Current task payload.
        definitions (dict): Parsed component definition mapping.
        context (dict): Rendering context containing image alias mappings.
    """
    log.info("Registering components with the Database")
    log.debug("Registering components with the Database", details=definitions)

    deployment_details = deepcopy(task_payload.deployment_details)  # Fixed: lowercase attribute

    # Dump context as metadata in DynamoDB in the build record
    update_item("build", deployment_details, metadata=context)

    # Register components with the API
    for component_name, definition in definitions.items():

        if not isinstance(definition, dict):
            raise ValueError(f"Invalid definition for component '{component_name}': expected a dictionary")

        deployment_details.component = component_name  # Fixed: lowercase attribute

        image_alias, image_id = __get_component_image(definition, context[CTX_CONTEXT].get("ImageAliases"))

        log.debug("Registering component with the database:", details=definition)

        if image_alias:
            log.debug("For component '{}', found image_alias '{}', image_id '{}'.".format(component_name, image_alias, image_id))

        register_item(
            "component",
            deployment_details,
            component_type=definition.get("Type", definitions.get("type", "Unknown")),
            image_alias=image_alias,
            image_id=image_id,
        )


def __compile_components(task_payload: TaskPayload, definitions: dict, context: dict) -> dict:
    """Validate and compile component definitions.

    Performs validation (enforcement conditional on configuration), renders each
    component, gathers validation / compilation errors and uploads compiled artefacts.

    Args:
        task_payload (TaskPayload): Current task payload.
        definitions (dict): Component definitions keyed by component name.
        context (dict): Resolved rendering context.

    Returns:
        dict: Standardized result structure (see :func:`__return`).
    """
    log.info("Compiling components")

    deployment_details = task_payload.deployment_details

    # Validate the components
    validation_results = __validate_definitions(deployment_details, definitions)

    # Collect together all the validation errors and warnings
    validation_errors = []
    validation_warnings = []
    for result in validation_results.values():
        validation_errors.extend(result["ValidationErrors"])
        validation_warnings.extend(result["ValidationWarnings"])

    # Fail compilation if validation is enforced and there are any validation errors
    if util.is_enforce_validation() and validation_errors:
        update_status("build", deployment_details, status=COMPILE_FAILED, message="One or more components have failed validation")

        return __return(
            status="error",
            message="One or more components have failed validation",
            validation_errors=validation_errors,
            validation_warnings=validation_warnings,
        )

    # Compile the components
    compile_results = __compile_component_definitions(
        deployment_details,
        definitions=definitions,
        context=context,
    )
    failed_components = {k: v for k, v in compile_results.items() if v["Status"] == "error"}
    successful_components = {k: v for k, v in compile_results.items() if v["Status"] == "ok"}

    log.debug("Updating build status")

    # Handle compilation failures
    if failed_components:
        log.error("One or more components have failed compilation")

        update_status("build", deployment_details, status=COMPILE_FAILED, message="One or more components have failed compilation")

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
        log.error("Error while uploading compiled components", details={"Error": str(e)})

        update_status("build", deployment_details, status=COMPILE_FAILED, message=f"Error while uploading compiled components: {e}")

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
    status: str,
    message: str,
    failed_components: dict = {},
    successful_components: dict = {},
    validation_errors: list[dict[str, Any]] = [],
    validation_warnings: list[dict[str, Any]] = [],
) -> dict:
    """Construct the normalized compilation result.

    NOTE: The default mutable arguments are intentionally preserved for legacy
    compatibility (callers do not mutate them). Future refactors may replace them
    with ``None`` + explicit initialization.

    Args:
        status (str): Overall result status (``"ok"`` or ``"error"``).
        message (str): Human-readable summary message.
        failed_components (dict, optional): Mapping of component -> failure record.
        successful_components (dict, optional): Mapping of component -> success record.
        validation_errors (list, optional): Aggregated validation error entries.
        validation_warnings (list, optional): Aggregated validation warning entries.

    Returns:
        dict: Dictionary containing ``Status``, ``Message``, successful ``Components`` and
        sorted ``CompilationErrors`` / ``CompilationWarnings`` lists.
    """
    errors = validation_errors + [
        {"Component": k, "Details": v["Details"], "Message": v["Message"]} for k, v in failed_components.items()
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


def __download_package(package: PackageDetails) -> str:
    """Download the package archive to a temporary file.

    Args:
        package (PackageDetails): Package metadata including bucket, region and key.

    Returns:
        str: Absolute path to a temporary ``.zip`` file on the local filesystem.

    Raises:
        ValueError: If the package key is missing.
        Exception: Propagates any underlying download errors after cleanup.
    """
    import tempfile

    bucket_name = package.bucket_name
    bucket_region = package.bucket_region
    version_id = package.version_id

    if package.key is None:
        raise ValueError("Package key is required")

    log.info("Downloading deployment pipeline package")
    log.debug(
        "Downloading object",
        details={
            "BucketName": bucket_name,
            "Key": package.key,
            "VersionId": version_id,
        },
    )

    bucket = MagicS3Client.get_bucket(Region=bucket_region, BucketName=bucket_name)

    extra_args = {}
    if package.version_id is not None:
        extra_args["VersionId"] = version_id

    # Create temporary file
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_file_path = temp_file.name
    temp_file.close()

    try:
        # Download directly to temp file
        bucket.download_file(Key=package.key, Filename=temp_file_path, ExtraArgs=extra_args)

        log.debug(f"Package downloaded to temporary file: {temp_file_path}")
        return temp_file_path

    except Exception as e:
        # Clean up temp file on error
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        raise e


def __upload_compiled_files(task_payload: TaskPayload, files: dict[str, str]) -> dict:
    """Upload compiled artefact and user files.

    Separates user file uploads (``/userfiles/`` path fragments) from artefact uploads
    to maintain the expected prefix layout (``files/`` vs ``artefacts/``).

    Args:
        task_payload (TaskPayload): Current task payload (for bucket metadata).
        files (dict[str, str]): Mapping of relative file name -> file body content (string / template output).

    Returns:
        dict: Mapping of original file name -> upload result metadata.
    """
    deployment_details = task_payload.deployment_details  # Fixed: lowercase attribute

    s3_artefacts_prefix = deployment_details.get_artefacts_key()
    s3_files_prefix = deployment_details.get_files_key()

    bucket_name = task_payload.package.bucket_name  # Fixed: lowercase attributes
    bucket_region = task_payload.package.bucket_region  # Fixed: lowercase attributes

    bucket = MagicS3Client.get_bucket(Region=bucket_region, BucketName=bucket_name)

    # collect results of the upload for status
    result: dict = {}

    # Upload component files to storage
    for file_name, body in files.items():
        if "/userfiles/" in file_name:
            upload_result = __upload_object(bucket, bucket_region, s3_files_prefix, file_name, body)
        else:
            upload_result = __upload_object(bucket, bucket_region, s3_artefacts_prefix, file_name, body)

        # save the result of the upload
        result[file_name] = upload_result  # Fixed: use upload_result instead of result

    # Return the results of the upload to the caller
    return result


def __get_component_image(definition: dict, image_aliases: dict) -> tuple[str | None, str | None]:
    """Resolve an image alias defined inside a component's configuration tree.

    Searches nested ``Configuration.*.Properties.ImageId.Fn::Pipeline::ImageId.Name``
    entries (using a compiled JMESPath expression) to translate an image alias into a
    concrete image id via the provided ``image_aliases`` map.

    Args:
        definition (dict): Component definition dictionary.
        image_aliases (dict): Mapping of image alias -> image id.

    Returns:
        tuple[str | None, str | None]: ``(image_alias, image_id)`` if resolved, otherwise
        ``(None, None)``.
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


def __validate_definitions(deployment_details: DeploymentDetails, definitions: dict[str, dict[str, Any]]) -> dict:
    """Validate each component definition.

    Issues component-level status updates. When enforcement is enabled any validation
    errors will mark components (and potentially the build) as failed and later cancel
    remaining compilation steps.

    Args:
        deployment_details (DeploymentDetails): Deployment metadata object.
        definitions (dict): Component definitions mapping.
        context (dict): Rendering / variable context.

    Returns:
        dict: Mapping of component name -> validation result structure.
    """

    log.info("Validating component definitions")

    results: dict[str, dict] = {}

    dd = deepcopy(deployment_details)

    any_errors = False
    for component_name, definition in definitions.items():

        dd.component = component_name.lower()

        update_status("component", dd, status=COMPILE_IN_PROGRESS, message="Validating component definition")

        # Validate the component
        result = validate_component(component_name, definition)

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
            message = "Component '{}' has one or more validation warnings".format(component_name)
            log.warn(
                message,
                details={"ValidationErrors": errors, "ValidationWarnings": warnings},
            )

        # Update the component status
        if errors:
            if util.is_enforce_validation():
                # Validation errors with enforcement
                update_status(
                    "component",
                    dd,
                    status=COMPILE_FAILED,
                    message="Component has failed validation",
                    details={"Consumable": definition["Type"]},
                )
            else:
                # Validation errors without enforcement
                update_status(
                    "component",
                    dd,
                    status=COMPILE_IN_PROGRESS,
                    message="Component has failed validation, but validation is not being enforced",
                    details={"Consumable": definition["Type"]},
                )
        elif warnings:
            # No errors but does have warnings
            update_status(
                "component",
                dd,
                status=COMPILE_IN_PROGRESS,
                message="Component validation completed with warnings",
                details={"Consumable": definition["Type"]},
            )
        else:
            # No warnings or errors
            update_status("component", dd, status=COMPILE_IN_PROGRESS, message="Component validation completed")

    # Cancel remaining compilations if validation is enforced and there are any validation errors
    if util.is_enforce_validation() and any_errors:

        for component_name, definition in results.items():

            dd.component = component_name.lower()

            result = results[component_name]

            # Only update the status if we wouldn't have previously set status to COMPILE_FAILED
            if not result["ValidationErrors"]:
                update_status(
                    "component",
                    dd,
                    status=COMPILE_FAILED,
                    message="Cancelled due to other build errors",
                    details={"Consumable": definition["Type"]},
                )

    return results


def __compile_component_definitions(
    deployment_details: DeploymentDetails,
    definitions: dict[str, dict[str, Any]],
    context: dict[str, Any],
) -> dict:
    """Render component definitions into final artefact representations.

    Also compiles application-level files (``_application`` pseudo component) before
    iterating per component name.

    Args:
        deployment_details (DeploymentDetails): Deployment metadata object.
        definitions (dict): Component definition mapping.
        context (dict): Rendering context.

    Returns:
        dict: Mapping of component (and ``_application``) -> compilation result record.
    """

    results: dict = {}

    results["_application"] = compile_app_files(definitions, context)

    dd = deepcopy(deployment_details)

    for component_name, definition in definitions.items():

        dd.component = component_name.lower()

        result = render_component(component_name, definitions, context)

        if result["Status"] == "ok":
            # Successful compilation
            update_status("component", dd, status=COMPILE_COMPLETE, details={"Consumable": definition["Type"]})
        else:
            # Errors during compilation
            update_status(
                "component",
                dd,
                status=COMPILE_FAILED,
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
) -> dict:
    """Persist a single compiled file to the target bucket / local storage.

    Uses platform abstraction (``MagicS3Client``) so local mode writes to the configured
    volume while remote mode writes to S3 with SSE and bucket-owner-full-control ACL.

    Args:
        bucket (Any): Underlying bucket (Magic bucket or boto3-like wrapper) supporting ``put_object``.
        bucket_region (str): Region of the S3 bucket (unused in local write but retained for logging).
        prefix (str): Logical object prefix (``files``, ``packages`` or ``artefacts`` style path).
        file_name (str): Relative file name produced during compilation.
        body (Any): File body (string / bytes) to upload.

    Returns:
        dict: Upload result metadata including ``BucketName``, ``BucketRegion``, ``Key`` and ``VersionId``.
    """
    sep = "/" if util.is_use_s3() else os.path.sep

    # The filename is coming from the same object used to pass to jinja.  Since
    # we had to make filenames use "/" for path seperators for Jinja, we will need
    # to replace them with the correct path seperator for the envinronment.

    key = "{}{}{}".format(prefix, sep, file_name.replace("/", sep))

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
