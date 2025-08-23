# use boto3 to connect to DynamoDB, get a list of all tables, then delete all tables
import boto3

import core_logging as logging
import core_framework as util

import core_helper.aws as aws

from core_db.registry.client import ClientFactsModel, ClientFactsFactory
from core_db.registry.portfolio import (
    PortfolioFactsModel,
    PortfolioFactsFactory,
    ContactFacts,
    ApproverFacts,
    ProjectFacts,
    OwnerFacts,
)
from core_db.registry.app import AppFactsModel, AppFactsFactory
from core_db.registry.zone import (
    ZoneFactsModel,
    ZoneFactsFactory,
    AccountFacts,
    RegionFacts,
    KmsFacts,
    SecurityAliasFacts,
    ProxyFacts,
)

from .bootstrap import *


def get_organization() -> dict:
    """
    Return organization information for the AWS Profile
    """

    organization = {"id": "", "account_id": "", "name": "", "email": ""}
    try:
        oc = aws.org_client()
        orginfo = oc.describe_organization()
        org = orginfo.get("Organization", {})
        organization.update(
            {
                "id": org.get("Id", ""),
                "account_id": org.get("MasterAccountId", ""),
                "email": org.get("MasterAccountEmail", ""),
            }
        )

        if organization["account_id"]:
            response = oc.describe_account(AccountId=organization["account_id"])
            organization["name"] = response.get("Account", {}).get("Name", "")

    except Exception:  # pylint: disable=broad-except
        pass

    return organization


def get_client_data(organization: dict, arguments: dict) -> ClientFactsModel:

    assert "client" in arguments

    client = arguments["client"]

    region = util.get_region()
    bucket_name = util.get_bucket_name()

    aws_account_id = organization["account_id"]

    client_model = ClientFactsFactory.get_model(client)
    cf = client_model(
        client=client,
        domain="my-domain.com",
        organization_id=organization["id"],
        organization_name=organization["name"],
        organization_account=organization["account_id"],
        organization_email=organization["email"],
        client_region=region,
        master_region=region,
        automation_account=aws_account_id,
        automation_bucket=bucket_name,
        automation_bucket_region=region,
        audit_account=aws_account_id,
        docs_bucket=bucket_name,
        security_account=aws_account_id,
        ui_bucket=bucket_name,
        scope_prefix="",
    )
    cf.save()

    return cf


def get_portfolio_data(
    client_data: ClientFactsModel, arguments: dict
) -> PortfolioFactsModel:

    assert "portfolio" in arguments

    portfllio_name = arguments["portfolio"]

    domain_name = client_data.Domain

    portfolio_model = PortfolioFactsFactory.get_model(client_data.Client)
    portfolio = portfolio_model(
        Client=client_data.Client,
        Portfolio=portfllio_name,
        Contacts=[ContactFacts(name="John Doe", email="john.doe@tmail.com")],
        Approvers=[
            ApproverFacts(
                name="Jane Doe", email="john.doe@tmail.com", roles=["admin"], sequence=1
            )
        ],
        Project=ProjectFacts(
            name="my-project", description="my project description", code="MYPRJ"
        ),
        Bizapp=ProjectFacts(
            name="my-bizapp", description="my bizapp description", code="MYBIZ"
        ),
        Owner=OwnerFacts(name="John Doe", email="john.doe@tmail.com"),
        Domain=f"my-app.{domain_name}",
        Tags={
            "BizzApp": "MyBizApp",
            "Manager": "John Doe",
        },
        Metadata={
            "misc": "items",
            "date": "2021-01-01",
        },
    )
    portfolio.save()

    return portfolio


def get_zone_data(client_data: ClientFactsModel, arguments: dict) -> ZoneFactsModel:

    automation_account_id = client_data.AutomationAccount
    automation_account_name = client_data.OrganizationName

    zone_model = ZoneFactsFactory.get_model(client_data.Client)
    zone = zone_model(
        Client=client_data.Client,
        Zone="my-automation-service-zone",
        AccountFacts=AccountFacts(
            Client=client_data.Client,
            AwsAccountId=automation_account_id,
            OrganizationalUnit="PrimaryUnit",
            AccountName=automation_account_name,
            Environment="prod",
            Kms=KmsFacts(
                AwsAccountId=automation_account_id,
                KmsKeyArn="arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012",
                KmsKey="alias/my-kms-key",
                DelegateAwsAccountIds=[automation_account_id],
            ),
            ResourceNamespace="my-automation-service",
            NetworkName="my-network-from-ciscos",
            VpcAliases={
                "primary-network": "my-cisco-network-primary-network-id",
                "secondary-network": "my-cisco-network-secondary-network-id",
            },
            SubnetAliases={
                "ingress": "my-cisco-network-ingress-subnet-id",
                "workload": "my-cisco-network-workload-subnet-id",
                "egress": "my-cisco-network-egress-subnet-id",
            },
            Tags={"Zone": "my-automation-service-zone"},
        ),
        RegionFacts={
            "sin": RegionFacts(
                AwsRegion="ap-southeast-1",
                AzCount=3,
                ImageAliases={"imageid:latest": "ami-2342342342344"},
                MinSuccessfulInstancesPercent=100,
                SecurityAliases={
                    "internet": [
                        SecurityAliasFacts(
                            Type="cidr", Value="0.0.0.0/0", Description="Internet CIDR"
                        )
                    ],
                    "intranet": [
                        SecurityAliasFacts(
                            Type="cidr",
                            Value="192.168.0.0/16",
                            Description="Global CIDR 1",
                        ),
                        SecurityAliasFacts(
                            Type="cidr", Value="10.0.0.0/8", Description="Global CIDR 2"
                        ),
                    ],
                },
                SecurityGroupAliases={
                    "alias1": "aws_sg_ingress",
                    "alias2": "aws-sg-egress-groups",
                },
                Proxy=[
                    ProxyFacts(
                        Host="myprox.proxy.com",
                        Port=8080,
                        Url="http://proxy.acme.com:8080",
                        NoProxy="10.0.0.0/8,192.168.0.0/16,*acme.com",
                    )
                ],
                ProxyHost="myprox.proxy.com",
                ProxyPort=8080,
                ProxyUrl="http://proxy.acme.com:8080",
                NoProxy="127.0.0.1,localhost,*.acme.com",
                NameServers=["192.168.1.1"],
                Tags={"Region": "sin"},
            )
        },
        Tags={"Zone": "my-automation-service-zone"},
    )
    zone.save()

    return zone


def get_app_data(
    portfolio_data: PortfolioFactsModel, zone_data: ZoneFactsModel, arguments: dict
) -> AppFactsModel:

    # The client/portfolio is where this BizApp that this Deployment is for.
    # The Zone is where this BizApp component will be deployed.

    client = portfolio_data.Client
    portfolio = portfolio_data.Portfolio
    app = arguments["app"]

    client_portfolio_key = f"{client}:{portfolio}"

    apps_model = AppFactsFactory.get_model(client_portfolio_key)
    app = apps_model(
        ClientPortfolio=client_portfolio_key,
        AppRegex=f"^prn:{portfolio}:{app}:.*:.*$",
        Zone=zone_data.Zone,
        Name="test application",
        Environment="prod",
        ImageAliases={"image1": "awsImageID1234234234"},
        Repository="https://github.com/my-org/my-portfolio-my-app.git",
        Region="sin",
        Tags={"Disposition": "Testing"},
        Metadata={"misc": "items"},
    )

    app.save()

    return app


def initialize(arguments: dict):

    if not bootstrap_dynamo():
        raise Exception("Failed to bootstrap DynamoDB")

    org_data = get_organization()

    client_data: ClientFactsModel = get_client_data(org_data, arguments)
    zone_data: ZoneFactsModel = get_zone_data(client_data, arguments)
    portfolio_data: PortfolioFactsModel = get_portfolio_data(client_data, arguments)
    app_data: AppFactsModel = get_app_data(portfolio_data, zone_data, arguments)

    return client_data, zone_data, portfolio_data, app_data
