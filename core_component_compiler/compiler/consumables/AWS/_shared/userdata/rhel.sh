if [ ! -f /usr/bin/amazon-ssm-agent ]; then
	yum install -y https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/linux_amd64/amazon-ssm-agent.rpm
	systemctl enable amazon-ssm-agent
	systemctl start amazon-ssm-agent
	echo "amazon-ssm-agent installation done"
fi

if [ ! -f /opt/aws/bin/cfn-signal ]; then

	if [ ! -f /usr/bin/cfn-signal ]; then

		echo "Installing aws-cfn-bootstrap for rhel."

		# Required to install deps to install aws-cfn-bootstrap
#		if [[ $(rpm -q epel-release) =~ "not installed" ]]; then
#			echo "Installing epel-release - not installed."
#			rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
#		fi

		# latest pip not compatible with python2 (rhel6).
		# See https://github.com/pypa/pip/issues/5152
		yum install -y python2
		yum install -y python2-pip
		ln -s /usr/bin/python2 /usr/bin/python
		# Ran into issue with older pips.
		#python -m pip install --upgrade pip

		# FIXME ImportError: cannot import name main - https://github.com/pypa/pip/issues/5240
#		pip3 install docutils
		# pip instlal docutils does not remove urllib3 package completely, failing to do system update via yum
		#rpm -e --nodeps python-urllib3
#		pip3 install pystache argparse python-daemon requests awscli boto3 boto
#		pip3 install pystache argparse requests awscli boto3 boto
#		pip3 --version

		#All rhel instances should have ansible installed. 
#		pip3 install ansible
		yum install ansible -y
		export PATH=/root/.local/bin/:$PATH
        
		# Install aws-cfn-bootstrap
		cd /opt
		curl -O https://s3.amazonaws.com/cloudformation-examples/aws-cfn-bootstrap-py3-latest.tar.gz
		tar -xvpf aws-cfn-bootstrap-py3-latest.tar.gz
		cd aws-cfn-bootstrap-2.0/
		python3 setup.py build
		python3 setup.py install
		ln -s /usr/local/init/redhat/cfn-hup /etc/init.d/cfn-hup
		chmod 775 /usr/local/init/redhat/cfn-hup

		echo "Finished installing aws-cfn-bootstrap for rhel."

	fi

	echo "symlinking cfn scripts into /opt/aws/bin for userdata script compatibility."

	# TODO Confirm necessity for these symlinks.
	mkdir -p /opt/aws/bin
	ln -s /usr/local/bin/cfn-hup /opt/aws/bin/cfn-hup
	ln -s /usr/local/bin/cfn-init /opt/aws/bin/cfn-init
	ln -s /usr/local/bin/cfn-signal /opt/aws/bin/cfn-signal
	ln -s /usr/local/bin/cfn-elect-cmd-leader /opt/aws/bin/cfn-elect-cmd-leader
	ln -s /usr/local/bin/cfn-get-metadata /opt/aws/bin/cfn-get-metadata
	ln -s /usr/local/bin/cfn-send-cmd-event /opt/aws/bin/cfn-send-cmd-event
	ln -s /usr/local/bin/cfn-send-cmd-result /opt/aws/bin/cfn-send-cmd-result

else

	echo "aws-cfn-bootstrap already installed on this instance, skipping."

fi
