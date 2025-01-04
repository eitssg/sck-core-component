import pytest
import os

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


def load_sample(sample_name: str) -> str:

    dirname = os.path.dirname(os.path.realpath(__file__))
    fn = os.path.join(dirname, "samples", sample_name)
    with open(fn, "r") as f:
        data = f.read()
    return data


@pytest.mark.parametrize("sample_name", samples)
def test_sample(sample_name: str):

    base_name = os.path.dirname(os.path.realpath(__file__))

    body = load_sample(sample_name)

    print("-------------------------------------")
    print(sample_name)
    print(body)
    print()

    # remove the contents from the components folder
    components_folder = os.path.join(base_name, "components")
    os.system(f"cd {components_folder} && DEL * /Q")

    fn = os.path.join(components_folder, sample_name)
    with open(fn, "w") as f:
        f.write(body)

    os.system(f"dir {components_folder}")

    print("-------------------------------------")

    assert True
