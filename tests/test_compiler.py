import pytest
import os
import shutil
import zipfile
import re

import core_framework as util

from core_db.facter import get_facts

from core_framework.models import TaskPayload, PackageDetails

from core_framework.constants import V_PACKAGE_ZIP

from core_helper.magic import MagicS3Client

from .data_for_testing import initialize

from core_component import pipeline_compiler

from .bootstrap import *  # noqa: F401


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


@pytest.fixture(scope="module")
def package_package():

    copy_sample("s3-bucket-quickstart.yaml")

    # Typical lifecycle is: -> package -> upload -> compile -> deploy -> teardown
    # This is the "package" step.  Create the zip file

    dirname = os.path.dirname(os.path.realpath(__file__))
    fn = os.path.join(dirname, V_PACKAGE_ZIP)

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


@pytest.fixture(scope="module")
def upload_package(task_payload: TaskPayload, package_package: str) -> PackageDetails:

    assert isinstance(task_payload, TaskPayload)
    assert isinstance(package_package, str)

    # Typical lifecycle is: -> package -> upload -> compile -> deploy | plan -> deploy | apply -> teardown
    # This is the "upload" step

    # arguments are collected from the commandline.

    state_details = task_payload.package

    bucket = MagicS3Client(Region=state_details.bucket_region).Bucket(state_details.bucket_name)

    try:
        # package.zip should be small.  The whole thing is read into memory.  a few MB is ok.  but 100MB is not.
        with open(package_package, "rb") as f:
            bucket.put_object(Key=state_details.key, Body=f.read())
    except Exception as e:
        print(e)
        pytest.fail("Failed to upload package")

    # we return the task action

    return task_payload.package


@pytest.fixture(scope="module")
def facts(task_payload: TaskPayload, arguments: dict):

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


def test_run_pl_compile(bootstrap_dynamo, task_payload: TaskPayload, upload_package: PackageDetails, facts: dict):

    assert isinstance(task_payload, TaskPayload)
    assert isinstance(upload_package, PackageDetails)
    assert isinstance(facts, dict)

    response = pipeline_compiler(task_payload.model_dump(), None)

    assert response is not None
