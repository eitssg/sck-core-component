{% from "AWS/_shared/macros/win_events.j2" import win_events with context %}
{{ win_events() | indent(0) }}
try {
    Invoke-LogVerbose "Executing Sysprep"
    powershell.exe $ENV:ProgramData\Amazon\EC2-Windows\Launch\Scripts\InitializeInstance.ps1 -Schedule
    powershell.exe $ENV:ProgramData\Amazon\EC2-Windows\Launch\Scripts\SysprepInstance.ps1 -NoShutdown
    exit 0
}
catch [System.Exception] {
    Invoke-LogError "Sysprep Failed"
    exit 1
}