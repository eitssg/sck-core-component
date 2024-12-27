"""Description: Compile a deployspec package into actions and templates.

# Extracts package files to a location in S3
# Parses and compiles the package deployspec (deployspec.yml)
# Uploads actions to S3
"""

from typing import Any

import io
import os
import re
import core_helper.aws as aws
import jmespath
import traceback
import zipfile as zip
import json

import core_logging as log

import core_framework as util
from core_framework.constants import (
    ENV_ENFORCE_VALIDATION,
    ENV_ENVIRONMENT,
    SCOPE_PORTFOLIO,
    SCOPE_APP,
    SCOPE_BRANCH,
    SCOPE_BUILD,
    V_LOCAL,
    V_PACKAGE_ZIP,
)

from core_framework.models import TaskPayload, PackageDetails
from core_framework.magic import MagicBucket

from core_db.dbhelper import (
    register_item,
    update_status,
    update_item,
    get_facts_by_identity,
)

from .preprocessor import load_user_variables, run
from .compiler import combine_result_files, compile_app_files, render_component
from .validator import validate_component


def handler(event: dict, context: dict | None) -> dict:
    """AWS Lambda handler function."""

    task_payload = TaskPayload(**event)

    # Update config (global)
    # os.environ["OUTPUT_PATH"] = package.get("OutputPath", "")
    # os.environ["PLATFORM_PATH"] = package.get("PlatformPath", "")

    # Setup logging (global)
    log.setup(task_payload.Identity or "unknown")

    # Execute
    return execute(task_payload)


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

    try:
        deployment_details = task_payload.DeploymentDetails

        branch_prn = deployment_details.get_branch_prn()
        build_prn = deployment_details.get_build_prn()

        # Register branch and build with the API
        if not deployment_details.Branch or not deployment_details.Build:
            return {
                "Status": "error",
                "Message": "Branch and Build details are required",
            }

        register_item(branch_prn, deployment_details.Branch)
        register_item(build_prn, deployment_details.Build, status="COMPILE_IN_PROGRESS")

        facts = __load_facts(task_payload)

        update_status(build_prn, "COMPILE_IN_PROGRESS", "Build compilation started")

        files = __download_package(task_payload.Package)

        definitions, variables = __run_preprocessor(task_payload, facts, files)

        compile_context = __construct_compile_context(task_payload, facts, variables)

        __register_components(task_payload, definitions, compile_context)

        result = __compile_components(task_payload, facts, definitions, compile_context)

        update_status(build_prn, "COMPILE_COMPLETE")

        return result

    except CompileException as e:
        try:
            update_status(build_prn, "COMPILE_FAILED", str(e.message))
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
            update_status(build_prn, "COMPILE_FAILED", str(e))
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


def __load_facts(task_payload: TaskPayload) -> dict:

    deployment_details = task_payload.DeploymentDetails

    # Retrieve deployment facts about this app build
    facts = get_facts_by_identity(
        deployment_details.Client, deployment_details.get_identity()
    )

    if "EnforceValidation" not in facts:
        facts["EnforceValidation"] = (
            os.getenv(ENV_ENFORCE_VALIDATION, "false").lower() == "true"
        )
    if "Environment" not in facts:
        facts["Environment"] = os.getenv(ENV_ENVIRONMENT, "prod")

    return facts


def __run_preprocessor(
    task_payload: TaskPayload, facts: dict[str, Any], files: dict[str, Any]
) -> tuple[dict, dict]:
    # Render the component definition files
    try:

        deployment_details = task_payload.DeploymentDetails
        build_prn = deployment_details.get_build_prn()

        preprocessor_context = {
            "context": {
                **facts,
                **deployment_details.model_dump(),
            }
        }
        variables = load_user_variables(files, preprocessor_context)

        preprocessor_context["vars"] = variables

        definitions = run(files, preprocessor_context)

        return definitions, variables

    except Exception as e:
        update_status(
            build_prn, "COMPILE_FAILED", "Error processing component definition files"
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


def __register_components(
    task_payload: TaskPayload, definitions: dict, compile_context: dict
):

    deployment_details = task_payload.DeploymentDetails
    build_prn = deployment_details.get_build_prn()

    # Dump context as metadata in DynamoDB
    update_item(prn=build_prn, context=json.dumps(compile_context))

    # Register components with the API
    for component_name, definition in definitions.items():

        component_prn = "{}:{}".format(build_prn, component_name)
        image_alias, image_id = __get_component_image(
            definition, compile_context["context"]["ImageAliases"]
        )

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
    task_payload: TaskPayload, facts: dict, definitions: dict, compile_context: dict
) -> dict:

    deployment_details = task_payload.DeploymentDetails
    build_prn = deployment_details.get_build_prn()

    # Validate the components
    validation_results = __validate_definitions(
        build_prn, definitions, compile_context, facts["Environment"]
    )

    # Collect together all the validation errors and warnings
    validation_errors = []
    validation_warnings = []
    for result in validation_results.values():
        validation_errors += result["ValidationErrors"]
        validation_warnings += result["ValidationWarnings"]

    # Fail compilation if validation is enforced and there are any validation errors
    if enforce_validation() and validation_errors:
        update_status(
            build_prn,
            "COMPILE_FAILED",
            "One or more components have failed validation",
        )

        return __return(
            status="error",
            message="One or more components have failed validation",
            validation_errors=validation_errors,
            validation_warnings=validation_warnings,
        )

    # Compile the components
    compile_results = __compile_component_defintiions(
        build_prn=build_prn,
        definitions=definitions,
        context=compile_context,
        environment=facts.get("Environment"),
    )
    failed_components = {
        k: v for k, v in compile_results.items() if v["Status"] == "error"
    }
    successful_components = {
        k: v for k, v in compile_results.items() if v["Status"] == "ok"
    }

    # Handle compliation failures
    if failed_components:
        update_status(
            build_prn,
            "COMPILE_FAILED",
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
        # Combine files from each compiled component
        compiled_files = combine_result_files(compile_results)

        # Upload files
        __upload_compiled_files(task_payload, compiled_files)

    except Exception as e:
        update_status(build_prn, "COMPILE_FAILED")
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

    return __return(
        "ok",
        message,
        failed_components,
        successful_components,
        validation_errors,
        validation_warnings,
    )


def enforce_validation():
    return os.environ.get(ENV_ENFORCE_VALIDATION, "true").lower() == "true"


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
        package (PackageDetails): _description_

    Returns:
        dict[str, Any]: _description_
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

    assert package.Key.endswith(V_PACKAGE_ZIP)

    if package.Mode == V_LOCAL:
        bucket = MagicBucket(bucket_name, bucket_region)
    else:
        s3 = aws.s3_resource(bucket_region)
        bucket = s3.Bucket(package.BucketName)

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


def __upload_compiled_files(task_payload: TaskPayload, files: dict):

    deployment_details = task_payload.DeploymentDetails
    scope = deployment_details.Scope or SCOPE_BUILD
    is_s3 = task_payload.Package.Mode != V_LOCAL

    s3_artefacts_prefix = util.get_artefacts_path(
        deployment_details, None, scope, is_s3
    )

    s3_build_files_prefix = util.get_files_path(deployment_details, None, scope, is_s3)

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
    # │   userfiles/
    # │   ├── file3.png
    # │   ├── file4.zip
    #
    # The package.zip is an archive containing all platform folder contents compnents, files and vars folders.

    for file_name, body in files.items():
        if "/userfiles/" in file_name:
            user_files[file_name] = body
        elif "/files/" in file_name:
            user_files[file_name] = body
        elif "/components/" in file_name:
            component_files[file_name] = body
        elif "/vars/" in file_name:
            component_files[file_name] = body

    bucket_name = task_payload.Package.BucketName
    bucket_region = task_payload.Package.BucketRegion

    # Get the bucket
    if not is_s3:
        bucket = MagicBucket(bucket_name, bucket_region)
    else:
        s3 = aws.s3_resource(bucket_region)
        bucket = s3.Bucket(bucket_name)

    # Upload component files to S3
    __upload_objects(bucket, bucket_region, s3_artefacts_prefix, component_files)

    # Upload userfiles to S3
    __upload_objects(bucket, bucket_region, s3_build_files_prefix, user_files)


def __get_component_image(definition: dict, image_aliases: dict) -> tuple:
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
    for resource_name, resource in definition["Configuration"].items():
        image_alias = expression.search(resource)
        if image_alias is None:
            continue
        image_id = image_aliases.get(image_alias, None)
        return (image_alias, image_id)
    return (None, None)


def __validate_definitions(
    build_prn: str, definitions: dict, context: dict, environment: str
) -> dict:
    results = {}

    any_errors = False
    for component_name in sorted(definitions):
        component_prn = "{}:{}".format(build_prn, component_name)
        definition = definitions[component_name]
        log.set_identity(component_prn)

        # Validate the component
        update_status(
            component_prn, "COMPILE_IN_PROGRESS", "Validating component definition"
        )

        result = validate_component(component_name, definitions, context)

        results[component_name] = result
        errors = result["ValidationErrors"]
        warnings = result["ValidationWarnings"]

        if errors:
            any_errors = True
            message = "Component '{}' has failed validation".format(component_name)
            log.error(
                message, details={"ValidationErrors": errors, "ValidationWarnings": warnings}
            )
        elif warnings:
            message = "Component '{}' has one or more validation warnings".format(
                component_name
            )
            log.warn(
                message, details={"ValidationErrors": errors, "ValidationWarnings": warnings}
            )

        # Update the component status
        if errors:
            if enforce_validation():
                # Validation errors with enforcement
                update_status(
                    component_prn,
                    "COMPILE_FAILED",
                    "Component has failed validation",
                    details={"Consumable": definition["Type"]},
                )
            else:
                # Validation errors without enforcement
                update_status(
                    component_prn,
                    "COMPILE_IN_PROGRESS",
                    "Component has failed validation, but validation is not being enforced",
                )
        elif warnings:
            # No errors but does have warnings
            update_status(
                component_prn,
                "COMPILE_IN_PROGRESS",
                "Component validation completed with warnings",
            )
        else:
            # No warnings or errors
            update_status(
                component_prn, "COMPILE_IN_PROGRESS", "Component validation completed"
            )

        log.reset_identity()

    # Cancel remaining compilations if validation is enforced and there are any validation errors
    if enforce_validation() and any_errors:
        for component_name in sorted(results):
            definition = definitions[component_name]
            result = results[component_name]
            component_prn = "{}:{}".format(build_prn, component_name)
            log.set_identity(component_prn)

            # Only update the status if we wouldn't have previously set status to COMPILE_FAILED
            if not result["ValidationErrors"]:
                update_status(
                    component_prn,
                    "COMPILE_FAILED",
                    "Cancelled due to other build errors",
                    details={"Consumable": definition["Type"]},
                )

            log.reset_identity()

    return results


def __compile_component_defintiions(
    build_prn: str, definitions: dict, context: dict, environment: str | None = None
) -> dict:
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
                "COMPILE_COMPLETE",
                details={"Consumable": definition["Type"]},
            )
        else:
            # Errors during compilation
            update_status(
                component_prn,
                "COMPILE_FAILED",
                message=result["Message"],
                details={"Consumable": definition["Type"]},
            )

        results[component_name] = result

    return results


def __construct_compile_context(
    task_payload: TaskPayload, facts: dict, variables: dict
) -> dict:

    deployment_details = task_payload.DeploymentDetails

    client = deployment_details.Client
    scope = deployment_details.Scope

    artefacts_bucket_name = util.get_artefact_bucket_name(client)
    artefacts_bucket_region = util.get_artefact_bucket_region
    s3_artefacts_prefix = util.get_artefact_key(deployment_details, None, scope)

    # Generate various context variables
    s3_artefacts_bucket_url = "https://s3-{}.amazonaws.com/{}".format(
        artefacts_bucket_region, artefacts_bucket_name
    )

    s3_files_bucket_url = "https://s3-{}.amazonaws.com/{}".format(
        artefacts_bucket_region, artefacts_bucket_name
    )

    # When building context replacement variables, we need to know if we are building for S3 or not
    for_s3 = task_payload.Package.Mode != V_LOCAL

    # For context rplacmeent variables
    s3_build_files_prefix = util.get_files_path(
        deployment_details, None, SCOPE_BUILD, for_s3
    )

    s3_branch_files_prefix = util.get_files_path(
        deployment_details, None, SCOPE_BRANCH, for_s3
    )

    s3_app_files_prefix = util.get_files_path(
        deployment_details, None, SCOPE_APP, for_s3
    )

    s3_portfolio_files_prefix = util.get_files_path(
        deployment_details, None, SCOPE_PORTFOLIO, for_s3
    )

    s3_shared_files_prefix = "files/shared"

    # Construct the compilation context
    compile_context = {
        "vars": variables,
        "context": {
            **facts,
            **deployment_details.model_dump(),
            # Artefacts
            "ArtefactsBucketName": artefacts_bucket_name,
            "ArtefactsBucketRegion": artefacts_bucket_region,
            "ArtefactsBucketUrl": s3_artefacts_bucket_url,
            "ArtefactsPrefix": s3_artefacts_prefix,
            # Files
            "FilesBucketName": artefacts_bucket_name,
            "FilesBucketRegion": artefacts_bucket_region,
            "FilesBucketUrl": s3_files_bucket_url,
            "BuildFilesPrefix": s3_build_files_prefix,
            "BranchFilesPrefix": s3_branch_files_prefix,
            "AppFilesPrefix": s3_app_files_prefix,
            "PortfolioFilesPrefix": s3_portfolio_files_prefix,
            "SharedFilesPrefix": s3_shared_files_prefix,
        },
    }

    return compile_context


def __upload_objects(bucket: Any, bucket_region: str, prefix: str, files: dict) -> dict:
    """
    Save the object to the targed Bucket.

    For "Local" mode, the bucket is a MagicBucket object.  So, look on your filesystem

    prefix is the path to the object.  It will be a path like files/**, pacakges/**, artefacts/**

    files is a dictionary of binary objets (byte arrays) indexed by the filename.

    Args:
        bucket (Any): S3 Bucket or MagicBucket object
        bucket_region (str): Region for the S3 bucket
        prefix (str): prefix for the object.  Will be a path like files/**, pacakges/**, artefacts/**
        files (dict): Dictionary of files to upload.

    Returns:
        dict: _description_
    """
    objects = {}
    # Process the package and retrieve the deployspec
    for file_name, file_contents in files.items():

        key = "{}/{}".format(prefix, file_name)
        key = key.replace("\\", "/")  # TODO Verify Mike's change here is required.
        log.debug(
            "Uploading file to S3",
            details={
                "BucketName": bucket.name,
                "BucketRegion": bucket_region,
                "Key": key,
            },
        )

        object = bucket.put_object(
            Body=file_contents,
            Key=key,
            ServerSideEncryption="AES256",
            ACL="bucket-owner-full-control",
        )

        objects[file_name] = {
            "BucketName": bucket.name,
            "BucketRegion": bucket_region,
            "Key": key,
            "VersionId": object.version_id,
        }

    return objects
