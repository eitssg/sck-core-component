import core_framework as util

import core_helper.aws as aws

from core_db.registry.client import ClientActions, ClientFact
from core_db.registry.portfolio import (
    ApproverFactsItem,
    ContactFactsItem,
    OwnerFactsItem,
    PortfolioFact,
    PortfolioActions,
    ProjectFactsItem,
)
from core_db.registry.app import AppFact, AppActions
from core_db.registry.zone import (
    ZoneFact,
    ProxyFactsItem,
    SecurityAliasFactsItem,
    KmsFactsItem,
    AccountFactsItem,
    RegionFactsItem,
    ZoneActions,
)

client = util.get_client() or "core"


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


def get_client_data(organization: dict, arguments: dict) -> ClientFact:
    global client

    assert "client" in arguments

    client = arguments["client"]

    region = util.get_region()
    bucket_name = util.get_bucket_name()

    aws_account_id = organization["account_id"]

    cf = ClientFact(
        Client=client,
        Domain="my-domain.com",
        OrganizationId=organization["id"],
        OrganizationName=organization["name"],
        OrganizationAccount=organization["account_id"],
        OrganizationEmail=organization["email"],
        ClientRegion=region,
        MasterRegion=region,
        AutomationAccount=aws_account_id,
        BucketName=bucket_name,
        BucketRegion=region,
        AuditAccount=aws_account_id,
        DocsBucketName=bucket_name,
        SecurityAccount=aws_account_id,
        UiBucketName=bucket_name,
        Scope="",
    )
    ClientActions.create(record=cf)

    return cf


def get_portfolio_data(client_data: ClientFact, arguments: dict) -> PortfolioFact:

    assert "portfolio" in arguments

    portfolio_name = arguments["portfolio"]

    domain_name = client_data.domain

    portfolio = PortfolioFact(
        Portfolio=portfolio_name,
        Contacts=[ContactFactsItem(Name="John Doe", Email="john.doe@tmail.com")],
        Approvers=[ApproverFactsItem(Name="Jane Doe", Email="john.doe@tmail.com", Roles=["admin"], Sequence=1)],
        Project=ProjectFactsItem(Name="my-project", Description="my project description", Code="MYPRJ"),
        Bizapp=ProjectFactsItem(Name="my-bizapp", Description="my bizapp description", Code="MYBIZ"),
        Owner=OwnerFactsItem(Name="John Doe", Email="john.doe@tmail.com"),
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
    PortfolioActions.create(client=client_data.client, record=portfolio)

    return portfolio


def get_zone_data(client_data: ClientFact, arguments: dict) -> ZoneFact:

    automation_account_id = client_data.automation_account or "123456789012"
    automation_account_name = client_data.organization_name

    zone = ZoneFact(
        Zone="my-automation-service-zone",
        AccountFacts=AccountFactsItem(
            AwsAccountId=automation_account_id,
            OrganizationalUnit="PrimaryUnit",
            AccountName=automation_account_name,
            Environment="prod",
            Kms=KmsFactsItem(
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
            "sin": RegionFactsItem(
                AwsRegion="ap-southeast-1",
                AzCount=3,
                ImageAliases={"imageid:latest": "ami-2342342342344"},
                MinSuccessfulInstancesPercent=100,
                SecurityAliases={
                    "internet": [SecurityAliasFactsItem(Type="cidr", Value="0.0.0.0/0", Description="Internet CIDR")],
                    "intranet": [
                        SecurityAliasFactsItem(
                            Type="cidr",
                            Value="192.168.0.0/16",
                            Description="Global CIDR 1",
                        ),
                        SecurityAliasFactsItem(Type="cidr", Value="10.0.0.0/8", Description="Global CIDR 2"),
                    ],
                },
                SecurityGroupAliases={
                    "alias1": "aws_sg_ingress",
                    "alias2": "aws-sg-egress-groups",
                },
                Proxy=[
                    ProxyFactsItem(
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
    ZoneActions.create(client=client_data.client, record=zone)

    return zone


def get_app_data(client_data: ClientFact, portfolio_data: PortfolioFact, zone_data: ZoneFact, arguments: dict) -> AppFact:

    # The client/portfolio is where this BizApp that this Deployment is for.
    # The Zone is where this BizApp component will be deployed.

    portfolio = portfolio_data.portfolio
    app = arguments["app"]

    app = AppFact(
        Portfolio=portfolio,
        App=app,
        AppRegex=f"^prn:{portfolio}:{app}:.*:.*$",
        Zone=zone_data.zone,
        Name="test application",
        Environment="prod",
        ImageAliases={"image1": "awsImageID1234234234"},
        Repository="https://github.com/my-org/my-portfolio-my-app.git",
        Region="sin",
        Tags={"Disposition": "Testing"},
        Metadata={"misc": "items"},
    )

    AppActions.create(client=client_data.client, record=app)

    return app


def initialize(arguments: dict):

    org_data = get_organization()

    client_data: ClientFact = get_client_data(org_data, arguments)
    zone_data: ZoneFact = get_zone_data(client_data, arguments)
    portfolio_data: PortfolioFact = get_portfolio_data(client_data, arguments)
    app_data: AppFact = get_app_data(client_data, portfolio_data, zone_data, arguments)

    return client_data, zone_data, portfolio_data, app_data
