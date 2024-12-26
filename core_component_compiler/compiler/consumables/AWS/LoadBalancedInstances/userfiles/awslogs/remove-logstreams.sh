#!/bin/sh -ex

# This script removes logstreams of other instances that are part of the loadbalanced instances component

# Get resource name
source /opt/pipeline/awslogs/resource_name.sh

# Remove all lines except for lines including resource name of this instance
# This will leave only relevant log streams
sed -i "/###$RESOURCE_NAME/ !d" /tmp/awslogs/instance-awslogs.conf

# Remove the ###<Resource Name> Prefix
sed -i "s/###$RESOURCE_NAME//g" /tmp/awslogs/instance-awslogs.conf

# Append configuration to awslogs.conf file
cat /tmp/awslogs/instance-awslogs.conf >> /tmp/awslogs/awslogs.conf
