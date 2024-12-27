if [ ! -f /opt/aws/bin/cfn-signal ]; then

	echo "[centos] symlinking cfn scripts into /opt/aws/bin for userdata script compatibility."

	# TODO Confirm necessity for these symlinks.
	mkdir -p /opt/aws/bin
	ln -s /usr/bin/cfn-hup /opt/aws/bin/cfn-hup
	ln -s /usr/bin/cfn-init /opt/aws/bin/cfn-init
	ln -s /usr/bin/cfn-signal /opt/aws/bin/cfn-signal
	ln -s /usr/bin/cfn-elect-cmd-leader /opt/aws/bin/cfn-elect-cmd-leader
	ln -s /usr/bin/cfn-get-metadata /opt/aws/bin/cfn-get-metadata
	ln -s /usr/bin/cfn-send-cmd-event /opt/aws/bin/cfn-send-cmd-event
	ln -s /usr/bin/cfn-send-cmd-result /opt/aws/bin/cfn-send-cmd-result

fi