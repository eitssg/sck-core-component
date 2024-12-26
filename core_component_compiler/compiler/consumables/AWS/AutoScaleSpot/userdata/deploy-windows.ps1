{% import "AWS/_shared/vars/names.j2" as names with context %}
{% from "AWS/_shared/macros/win_events.j2" import win_events with context %}
{% from "AWS/_shared/macros/win_stdlib.j2" import win_stdlib with context %}
<powershell>
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Force -ErrorAction SilentlyContinue
# Set up our variables

$ProxyUrl    = "{{ context.ProxyUrl }}"
$NoProxy     = "{{ context.NoProxy }}"
$NoProxyWin  = $NoProxy -replace ",", ";"

$Region     = "${AWS::Region}"
$StackId    = "${AWS::StackName}"
$Resource   = "LaunchConfiguration"
$ResourceToSignal = "AutoScalingGroup"

# Common Helper Functions
{{ win_events() | indent(0) }}
{{ win_stdlib() | indent(0) }}

# Begin Execution Phase
$logFile = "$ENV:SystemDrive\pipeline\cloudinit\logs\cloud-init-output.log"
$ErrorActionPreference = "Stop"
Start-Transcript -Path $logFile -Append -IncludeInvocationHeader

Set-PipelineEventLog

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

    cfn-signal.exe -e 1 --region $Region --stack $StackId --resource $ResourceToSignal

    exit 1
}

Stop-transcript

</powershell>
