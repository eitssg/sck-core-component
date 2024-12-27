# RHEL7 needs aws-cfn-bootstrap
{% if 'rhel' in image_name %}
{% include "AWS/_shared/userdata/rhel.sh" %}
{% endif %}

# Centos6 needs cfn-bootstrap links fixed up
{% if 'centos' in image_name %}
{% include "AWS/_shared/userdata/centos.sh" %}
{% endif %}