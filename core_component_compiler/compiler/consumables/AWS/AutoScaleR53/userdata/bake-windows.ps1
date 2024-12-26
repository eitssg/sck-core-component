{% import "AWS/_shared/vars/names.j2" as names with context %}
{% from "AWS/_shared/macros/win_events.j2" import win_events with context %}
{% from "AWS/_shared/macros/win_stdlib.j2" import win_stdlib with context %}
<powershell>
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Force -ErrorAction SilentlyContinue
# Set up our variables
# Proxy vars
$ProxyUrl    = "{{ context.ProxyUrl }}"
$NoProxy     = "{{ context.NoProxy }}"
$NoProxyWin  = $NoProxy -replace ",", ";"
# AWS Specific vars
$Region     = "${AWS::Region}"
$StackId    = "${AWS::StackName}"
$Resource   = "BakeInstance"
# Event vars


# Common Helper Functions
{{ win_events() | indent(0) }}
{{ win_stdlib() | indent(0) }}

# Primary wrapper for configuration
function Invoke-PipelineConfig {
    Set-PipelineEventLog
    Invoke-LogVerbose "=== Begin Automated Configuration Userdata ==="
    # Set DNS server
    Invoke-LogVerbose "DNS resolver configuration"
    {% if 'NameServers' in context %}
    {% for nameserver in context.NameServers %}
    Set-DnsClientServerAddress -InterfaceIndex 1 -ServerAddresses ({{ nameserver }})
    {% endfor %}
    {% endif %}

    # Setup proxies
    Trace-ProxyValues "Setting proxy system environment variables" $ProxyUrl $NoProxy
    setx /m HTTP_PROXY $ProxyUrl
    setx /m HTTPS_PROXY $ProxyUrl
    setx /m NO_PROXY $NoProxy

    Trace-ProxyValues "Setting proxy values for the current session" $ProxyUrl $NoProxy
    $env:HTTP_PROXY = $ProxyUrl
    $env:HTTPS_PROXY = $ProxyUrl
    $env:NO_PROXY = $NoProxy

    Trace-ProxyValues "Setting Windows proxies" $ProxyUrl $NoProxyWin
    Set-WindowsProxy $ProxyUrl $NoProxyWin

    Invoke-LogVerbose "Setting proxy for SSM"
    Set-SSMProxy $ProxyUrl
    Invoke-LogVerbose "Setting the CloudWatch logs agent proxy config"
    Invoke-LogVerbose "Writing the Pipeline environment variables out to file(s)"
    Set-PipelineInfo
    Invoke-LogVerbose "=== End Automated Configuration Userdata ==="
}

$logFile = "$ENV:SystemDrive\pipeline\cloudinit\logs\cloud-init-output.log"
$ErrorActionPreference = "Stop"
# Begin Execution Phase
if (!(Test-Path $(split-path $logFile -parent))) { 
    New-Item -ItemType Directory -Path $(split-path $logFile -parent)
}
Start-Transcript -Path $logFile -Append -IncludeInvocationHeader

Invoke-PipelineConfig

try {
    Invoke-LogVerbose "Executing cfn-init (region=$Region; stack=$StackId; resource=$Resource)"

    $exitCode = (Start-Process "cfn-init.exe" -ArgumentList "-v --region $Region --stack $StackId --resource $Resource --configsets default" -Wait -Passthru).ExitCode
    if ($exitCode) { throw "Exit code: $exitCode - Failed to execute cfn-init default step" }
    
    # We cannot do anything more here because cfn-init may cause instance to reboot

    exit 0
}
catch [System.Exception] {
    Invoke-LogError "$_"
    Invoke-LogError "Signalling CloudFormation with cfn-signal (error=1; region=$Region; stack=$StackId; resource=$Resource)"

    cfn-signal.exe -e 1 --region $Region --stack $StackId --resource $Resource

    exit 1
}

Stop-transcript

</powershell>
