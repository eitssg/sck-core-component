from importlib.metadata import packages_distributions
from core_framework.models import DeploymentDetails, PackageDetails, TaskPayload
from core_helper import MagicBucket, MagicS3Client
import pytest
import os

import core_logging as log
import core_framework as util

from core_component.handler import handler

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


def upload_package(task_payload: TaskPayload, sample_name: str):

    package = task_payload.package

    dirname = os.path.dirname(os.path.realpath(__file__))
    fn = os.path.join(dirname, "samples", sample_name)

    log.info("Uploading package", details=package.model_dump())

    bucket: MagicBucket = MagicS3Client().get_bucket(BucketName=package.bucket_name, Region=package.bucket_region)
    bucket.put_object(Filename=fn, Key=package.key)


def download_result(task_payload: TaskPayload, sample_name: str):

    package = task_payload.package

    dirname = os.path.dirname(os.path.realpath(__file__))
    result_dir = os.path.join(dirname, "results")
    os.makedirs(result_dir, exist_ok=True)
    fn = os.path.join(result_dir, sample_name + ".result.yaml")

    log.info("Downloading result", details=package.model_dump())

    bucket: MagicBucket = MagicS3Client().get_bucket(BucketName=package.bucket_name, Region=package.bucket_region)
    # bucket.download_file(Key=package.key + ".result.yaml", Filename=fn)


@pytest.fixture
def task_payload() -> TaskPayload:
    return TaskPayload(
        Task="deploy",
        DeploymentDetails=DeploymentDetails(
            Client=client,
            Portfolio="my-portfolio",
            App="my-application",
            Branch="dev",
            Build="001",
        ),
    )


@pytest.mark.parametrize("sample_name", samples)
def test_sample(sample_name: str, task_payload: TaskPayload):

    log.info("Beginning test_sample", sample=sample_name)

    # set the sample name in the task payload so the handler can find it
    dd = task_payload.deployment_details
    task_payload.package.set_key(dd, sample_name)

    upload_package(task_payload, sample_name)

    print(f"Compiling {sample_name}")

    details = handler(task_payload.model_dump(), None)

    download_result(task_payload, sample_name)

    log.info("Response Details", details=details)

    assert True
