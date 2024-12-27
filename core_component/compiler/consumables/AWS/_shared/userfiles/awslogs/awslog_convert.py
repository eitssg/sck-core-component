import argparse
import ConfigParser
import json
import os.path
from io import StringIO


def read_config(file):
    config = ConfigParser.RawConfigParser()

    try:
        config.read(file)
    except ConfigParser.MissingSectionHeaderError:
        with open(file, "r") as f:
            config.read_file(StringIO("[default]\n" + f.read()))

    return config


def _get_args():
    parser = argparse.ArgumentParser(
        description="parse awslogs config to cloudwatch agent config",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-a", "--aws-logs", required=True, help="awslogs home")
    parser.add_argument("-r", "--region", help="Region")
    parser.add_argument(
        "-o", "--output", help="config.json will be written into this output path"
    )
    return parser.parse_args()


def run(args):
    region = "ap-southeast-1" if args.region is None else args.region

    log_file = os.path.join(args.aws_logs, "etc", "awslogs.conf")
    log_files = [log_file]

    for subdir, dirs, files in os.walk(os.path.join(args.aws_logs, "etc", "config")):
        for file in files:
            log_files.append(os.path.join(args.aws_logs, "etc", "config", file))

    collect_list = []
    cw_logs = {}

    for log_file in log_files:
        logs = read_config(log_file)
        for key in logs.sections():
            # print(key)
            # print(config.has_option(key, 'log_stream_name'))
            # section = config[key]
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

    output = args.output if args.output is not None else "config.json"

    with open(output, "w") as f:
        json.dump(cw_config, f)


if __name__ == "__main__":
    run(_get_args())
