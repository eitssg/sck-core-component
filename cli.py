#!/usr/bin/python3

import argparse
import os
import re
import json

from component_compiler import handler


def _get_args():
    parser = argparse.ArgumentParser(
        description="Component Compiler for the Action Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-s", "--scope", help="Scope name", required=False)
    parser.add_argument(
        "-c", "--client", help="Client name for selecting config", required=True
    )
    parser.add_argument("-p", "--portfolio", help="Portfolio name", required=True)
    parser.add_argument("-a", "--app", help="Application name", required=True)
    parser.add_argument("-b", "--branch", help="Branch name", required=True)
    parser.add_argument("-n", "--build", help="Build number", required=True)
    parser.add_argument(
        "--mode", default=None, help="Mode of operation (default|local)"
    )
    parser.add_argument(
        "--compile-mode", default=None, help="Compile type (full|validate)"
    )
    parser.add_argument(
        "--aws-profile",
        help="Select which profile to use from your ~/.aws/credentials file.",
    )
    parser.add_argument("--app-path", help="Local app path (local mode only)")
    parser.add_argument("--facts-path", help="Facts path (local mode only)")
    parser.add_argument(
        "--bucket-region", default="ap-southeast-1", help="S3 Bucket Region"
    )
    parser.add_argument("--bucket-name", default=None, help="S3 Bucket Name")
    parser.add_argument("--s3-facts-prefix", default=None, help="S3 facts prefix")

    args = parser.parse_args()

    scope_prefix = "{}-".format(args.scope) if args.scope is not None else ""
    if args.bucket_name is None:
        args.bucket_name = "{}{}-core-automation-{}".format(
            scope_prefix, args.client, args.bucket_region
        )

    return args


def run(args):
    """
    Drives the CLI, supports different run Mode, i.e. default|local.
    """

    # Set for facter code. Needs to be flexible, since facts are packaged with lambda and deployed to aws.
    # See deploy.sh.
    # Later, added support for FACTS_S3_KEY_PREFIX, for lambdas to download from s3 to tmp folder.
    # If set, even when running from laptop, don't set FACTS_PATH.
    if args.s3_facts_prefix is not None:
        print("Setting FACTS_S3_KEY_PREFIX={}".format(args.s3_facts_prefix))
        os.environ["FACTS_S3_KEY_PREFIX"] = args.s3_facts_prefix
    else:
        if args.facts_path is None:
            os.environ["FACTS_PATH"] = "../../../{}-config".format(args.client)
            print("Setting FACTS_PATH={}".format(os.environ["FACTS_PATH"]))
        else:
            os.environ["FACTS_PATH"] = args.facts_path

    if args.aws_profile is not None:
        print("Setting AWS_PROFILE={}".format(args.aws_profile))
        os.environ["AWS_PROFILE"] = args.aws_profile

    branch_short_name = re.sub(r"[^a-z0-9\\-]", "-", args.branch.lower())[0:20].rstrip(
        "-"
    )

    package = {
        "BucketRegion": args.bucket_region,
        "BucketName": args.bucket_name,
        "Key": "packages/{}/{}/{}/{}/package.zip".format(
            args.portfolio, args.app, branch_short_name, args.build
        ),
        "VersionId": None,
    }

    if args.mode == "local":
        # In local mode, add another parameter to flag to the lambda that
        # We're in "local mode", and to not bother downloading/uploading to s3.
        if args.data_path is None:
            # TODO Can argparse handle this kind of conditional requirements?
            raise ValueError("app-path is required for local mode.")
        # Add params to the Package payload for the lambda.
        package["Mode"] = args.mode
        package["CompileMode"] = args.compile_mode
        package["PlatformPath"] = os.path.abspath(
            os.path.join(args.data_path, "platform")
        )
        # Verify that data_path is a valid application location (i.e. developer mistake).developer
        if not os.path.exists(package["PlatformPath"]):
            raise ValueError(
                "PlatformPath must exist, i.e. app-path must point to an actual app folder."
            )
        package["OutputPath"] = os.path.join(args.data_path, "_compiled")

    # Emulated payload for local lambda execution.
    event = {
        "Package": package,
        "Identity": "prn:{}:{}:{}:{}".format(
            args.portfolio, args.app, branch_short_name, args.build
        ),
        "DeploymentDetails": {
            "Portfolio": args.portfolio,
            "App": args.app,
            "Branch": args.branch,
            "BranchShortName": branch_short_name,
            "Build": args.build,
        },
    }

    response = handler(event, {})
    response_string = json.dumps(response, indent=4, sort_keys=True)

    if response["Status"] == "error":
        raise ValueError(response_string)

    print(response_string)

    f = open("compile-response.txt", "w")
    f.write(response_string)
    f.close()


if __name__ == "__main__":
    args = _get_args()
    run(args)
