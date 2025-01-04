import pytest
import os
import re

import core_framework as util

from core_db.facter import get_facts

from core_framework.models import TaskPayload, PackageDetails

from core_framework.constants import V_PACKAGE_ZIP

from core_helper.magic import MagicS3Client

from .data_for_testing import initialize

from core_component import pipeline_compiler


@pytest.fixture(scope="module")
def arguments():

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


def copy_sample(fn: str):

    dirname = os.path.dirname(os.path.realpath(__file__))

    os.system(f"del {os.path.join(dirname, 'components')}/* /Q")

    src = os.path.join(dirname, "samples", fn)
    dst = os.path.join(dirname, "components", fn)

    os.system(f"cp {src} {dst}")

    return dst


@pytest.fixture(scope="module")
def package_package():

    copy_sample("s3-bucket-quickstart.yaml")

    # Typical lifecycle is: -> package -> upload -> compile -> deploy -> teardown
    # This is the "package" step.  Create the zip file

    dirname = os.path.dirname(os.path.realpath(__file__))
    fn = os.path.join(dirname, V_PACKAGE_ZIP)

    # set current working directory to the location of this file
    files = " ".join(["components/*", "vars/*"])

    os.system(f"cd {dirname} && 7z a {fn} " + files)

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

    state_details = task_payload.Package

    bucket = MagicS3Client(Region=state_details.BucketRegion).Bucket(
        state_details.BucketName
    )

    try:
        # package.zip should be small.  The whole thing is read into memory.  a few MB is ok.  but 100MB is not.
        with open(package_package, "rb") as f:
            bucket.put_object(Key=state_details.Key, Body=f.read())
    except Exception as e:
        print(e)
        pytest.fail("Failed to upload package")

    # we return the task action

    return task_payload.Package


@pytest.fixture(scope="module")
def facts(task_payload: TaskPayload, arguments: dict):

    cf, zf, pf, af = initialize(arguments)

    deployment_details = task_payload.DeploymentDetails

    facts = get_facts(deployment_details)

    assert facts is not None

    assert facts["Client"] == cf.Client
    assert facts["Portfolio"] == pf.Portfolio
    assert facts["Zone"] == zf.Zone
    assert facts["AppRegex"] == af.AppRegex

    assert re.match(facts["AppRegex"], deployment_details.get_identity())

    return facts


def test_run_pl_compile(
    task_payload: TaskPayload, upload_package: PackageDetails, facts: dict
):

    assert isinstance(task_payload, TaskPayload)
    assert isinstance(upload_package, PackageDetails)
    assert isinstance(facts, dict)

    response = pipeline_compiler(task_payload.model_dump(), None)

    assert response is not None
