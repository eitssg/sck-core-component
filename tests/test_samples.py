import pytest
import os
import re
import shutil
import zipfile

import core_logging as log
import core_framework as util

from core_framework.models import DeploymentDetails, PackageDetails, TaskPayload
from core_helper import MagicBucket, MagicS3Client
from core_db.facter import get_facts

from core_component.handler import handler

from .data_for_testing import initialize
from .bootstrap import bootstrap_dynamo


@pytest.fixture(scope="module")
def arguments():
    """Simulate commandline arguments parsing."""

    client = util.get_client()  # from the --client paramter

    task = "compile"  # from the "command" positional parameter "compile" phase
    portfolio = "my-portfolio"  # from the -p, --portfolio parameter
    app = "my-app"  # from the -a, --app parameter
    branch = "my-branch"  # from the -b --branch parameter
    build = "pipe-build"  # from the -i, --build parameter
    automation_type = "pipeline"  # from the --automation-type parameter

    # commandline example:

    # core --client my-client compile -p my-portfolio -a my-app -b my-branch -i dp-build --automation-type deployspec

    state = {
        "client": client,
        "task": task,
        "portfolio": portfolio,
        "app": app,
        "branch": branch,
        "build": build,
        "automation_type": automation_type,
    }

    return state


def delete_component_files():

    dirname = os.path.dirname(os.path.realpath(__file__))

    # Clean out existing component files
    components_dir = os.path.join(dirname, "components")
    if os.path.isdir(components_dir):
        for entry in os.listdir(components_dir):
            path = os.path.join(components_dir, entry)
            try:
                if os.path.isfile(path) or os.path.islink(path):
                    os.unlink(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
            except Exception as e:
                raise RuntimeError(f"Failed cleaning components directory entry '{path}': {e}")


def copy_sample(fn: str):

    delete_component_files()

    dirname = os.path.dirname(os.path.realpath(__file__))

    src = os.path.join(dirname, "samples", fn)
    dst = os.path.join(dirname, "components", fn)

    # Replace shell copy with pure Python for cross-platform safety
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
    except Exception as e:
        raise RuntimeError(f"Failed to copy sample file '{src}' to '{dst}': {e}")

    return dst


def package_sample(sample_name: str) -> str:

    copy_sample(sample_name)

    # Typical lifecycle is: -> package -> upload -> compile -> deploy -> teardown
    # This is the "package" step.  Create the zip file

    dirname = os.path.dirname(os.path.realpath(__file__))
    fn = os.path.join(dirname, "package.zip")

    # Build the zip archive using the stdlib (replaces external 7z dependency)
    added = 0
    with zipfile.ZipFile(fn, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel_root in ("components", "vars"):
            root_path = os.path.join(dirname, rel_root)
            if not os.path.isdir(root_path):
                continue
            for root, _dirs, files in os.walk(root_path):
                for name in files:
                    file_path = os.path.join(root, name)
                    # Ensure forward slashes inside archive for consistency across platforms
                    arcname = os.path.relpath(file_path, dirname).replace(os.path.sep, "/")
                    zf.write(file_path, arcname)
                    added += 1

    if added == 0:
        raise RuntimeError("Package archive is empty; no files found in components/ or vars/ directories")

    # Remember 3 tasks are supported: deploy, plan, apply"
    # you will need to upload the appropriate files in your package.
    # deployspec.yaml, planspec.yaml, applyspec.yaml
    # Each spec must contain the appropriate actions for the task.

    return fn


@pytest.fixture(scope="module")
def task_payload(arguments: dict) -> TaskPayload:

    assert isinstance(arguments, dict)

    # Typical lifecycle is: -> package -> upload -> compile -> deploy -> teardown
    # This is the "deploy" step

    task_payload = TaskPayload.from_arguments(**arguments)

    return task_payload


def upload_package(task_payload: TaskPayload, sample_name: str) -> PackageDetails:

    package_sample(sample_name)

    # Typical lifecycle is: -> package -> upload -> compile -> deploy | plan -> deploy | apply -> teardown
    # This is the "upload" step

    # arguments are collected from the commandline.

    state_details = task_payload.package

    try:
        dirname = os.path.dirname(os.path.realpath(__file__))
        fn = os.path.join(dirname, "package.zip")

        bucket = MagicS3Client(Region=state_details.bucket_region).Bucket(state_details.bucket_name)

        # package.zip should be small.  The whole thing is read into memory.  a few MB is ok.  but 100MB is not.
        with open(fn, "rb") as f:
            bucket.put_object(Key=state_details.key, Body=f)

    except Exception as e:
        print(e)
        pytest.fail("Failed to upload package")

    # we return the task action

    return task_payload.package


@pytest.fixture(scope="module")
def facts(task_payload: TaskPayload, arguments: dict, bootstrap_dynamo):

    cf, zf, pf, af = initialize(arguments)

    deployment_details = task_payload.deployment_details

    facts = get_facts(deployment_details)

    assert facts is not None

    assert facts["Client"] == cf.client
    assert facts["Portfolio"] == pf.portfolio
    assert facts["Zone"] == zf.zone
    assert facts["AppRegex"] == af.app_regex

    assert re.match(facts["AppRegex"], deployment_details.get_identity())

    return facts


samples = [
    "applicationloadbalancer-quickstart.yaml",
    "autoscale-alb-quickstart.yaml",
    "autoscale-clb-quickstart.yaml",
    "cluster-quickstart.yaml",
    "component-example.yaml",
    "documentdb-quickstart.yaml",
    "dynamodb-payperrequest.yaml",
    "dynamodb-quickstart.yaml",
    "elasticache-redis-quickstart.yaml",
    "instance-quickstart.yaml",
    "loadbalancedinstances-quickstart.yaml",
    "rds-aurora-mysql-quickstart.yaml",
    "rds-aurora-postgresql-quickstart.yaml",
    "rds-mariadb-quickstart.yaml",
    "rds-mssql-quickstart.yaml",
    "rds-mysql-quickstart.yaml",
    "rds-oracle-quickstart.yaml",
    "rds-postgresql-quickstart.yaml",
    "redshift-quickstart.yaml",
    "s3-bucket-branch.yaml",
    "s3-bucket-lifecycle.yaml",
    "s3-bucket-quickstart.yaml",
    "s3-storage-quickstart.yaml",
    "secret-quickstart.yaml",
    "serverless-quickstart.yaml",
    "serverless-s3-subscriptions.yaml",
    "serverless-scheduled.yaml",
    "sqs-queue-quickstart.yaml",
    "staticwebsite-quickstart.yaml",
    "staticwebsite-v2-quickstart.yaml",
]

client = util.get_client() or "core"


def load_sample(sample_name: str) -> str:

    dirname = os.path.dirname(os.path.realpath(__file__))
    fn = os.path.join(dirname, "samples", sample_name)
    with open(fn, "r") as f:
        data = f.read()
    return data


def download_result(task_payload: TaskPayload, sample_name: str):

    artefacts = task_payload.state

    dirname = os.path.dirname(os.path.realpath(__file__))
    result_dir = os.path.join(dirname, "results")
    os.makedirs(result_dir, exist_ok=True)
    fn = os.path.join(result_dir, sample_name + ".result.yaml")

    log.info("Downloading result", details=artefacts.model_dump())

    bucket: MagicBucket = MagicS3Client().get_bucket(BucketName=artefacts.bucket_name, Region=artefacts.bucket_region)
    prefix = artefacts.key
    # bucket.download_file(Key=artefacts.key + ".result.yaml", Filename=fn)


@pytest.mark.parametrize("sample_name", samples)
def test_sample(sample_name: str, task_payload: TaskPayload, facts: dict):

    log.info("Beginning test_sample", sample=sample_name)

    upload_package(task_payload, sample_name)

    print(f"Compiling {sample_name}")

    details = handler(task_payload.model_dump(), None)

    download_result(task_payload, sample_name)

    log.info("Response Details", details=details)

    assert True
