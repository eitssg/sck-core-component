import argparse
import configparser
import json
import os
from io import StringIO


def read_config(file):
    config = configparser.RawConfigParser()

    try:
        config.read(file)
    except configparser.MissingSectionHeaderError:
        with open(file, "r") as f:
            config.read_file(StringIO("[default]\n" + f.read()))

    return config


def _get_args():
    parser = argparse.ArgumentParser(
        description="parse awslogs config to cloudwatch agent config",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-a", "--aws-logs", required=True, help="<folder> name where <folder>/etc/awslogs.conf is located.")
    parser.add_argument(
        "-r",
        "--region",
        help="Region where the CloudWatch logs will be sent.  Defaults to 'ap-southeast-1'.",
        default="ap-southeast-1",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Name of the output file to be written.  Defaults to 'config.json' in the current folder.",
        default="config.json",
    )
    return parser.parse_args()


def run(args):
    # Set defaults if the parser had an issue
    region = args.region if args.region is not None else "ap-southeast-1"
    output = args.output if args.output is not None else "config.json"

    log_file = os.path.join(args.aws_logs, "etc", "awslogs.conf")

    if not os.path.isfile(log_file):
        raise FileNotFoundError(f"Cannot find awslogs config file: {log_file}")

    base_path = os.path.dirname(output)
    if base_path and not os.path.exists(base_path):
        os.makedirs(base_path)

    # Error if the folder is not writable
    if not os.access(base_path if base_path != "" else ".", os.W_OK):
        raise PermissionError(f"Cannot write to folder: {base_path}")

    log_files = [log_file]

    for subdir, dirs, files in os.walk(os.path.join(args.aws_logs, "etc", "config")):
        for file in files:
            log_files.append(os.path.join(args.aws_logs, "etc", "config", file))

    collect_list = []
    cw_logs = {}

    for log_file in log_files:
        logs = read_config(log_file)
        for key in logs.sections():
            if logs.has_option(key, "log_stream_name"):
                entry = {
                    "file_path": logs.get(key, "file"),
                    "log_group_name": logs.get(key, "log_group_name"),
                    "log_stream_name": logs.get(key, "log_stream_name"),
                }
                if logs.has_option(key, "datetime_format"):
                    datetime = logs.get(key, "datetime_format")
                    entry["timestamp_format"] = datetime

                collect_list.append(entry)

    cw_config = {"agents": {"region": region}}

    if len(collect_list) != 0:
        cw_config["logs"] = {
            "log_stream_name": "{instance_id}",
            "logs_collected": {"files": {"collect_list": collect_list}},
        }

    with open(output, "w") as f:
        json.dump(cw_config, f)


if __name__ == "__main__":
    try:
        run(_get_args())
    except Exception as e:
        print(f"Error: {e}")
        exit(1)
