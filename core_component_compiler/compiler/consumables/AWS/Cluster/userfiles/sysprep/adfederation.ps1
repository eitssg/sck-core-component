{% from "AWS/_shared/macros/win_events.j2" import win_events with context %}
{{ win_events() | indent(0) }}
# Environment Variable Import
. "C:\pipeline\deployment_information.ps1"

$GlobalAccessGroup = "$PIPELINE_ENVIRONMENT" + _ + "$PIPELINE_PORTFOLIO" + _ + "ACCESS"
$PortfolioAccessGroup = "$PIPELINE_ENVIRONMENT" + _ + "$PIPELINE_PORTFOLIO" + _ + "ACCESS"
$ApplicationAccessGroup = "$PIPELINE_ENVIRONMENT" + _ + "$PIPELINE_PORTFOLIO" + _ + "$PIPELINE_APP" + _ + "ACCESS"
$LocalAccessGroup = "Remote Desktop Users"

$GlobalSudoersGroup = "$PIPELINE_ENVIRONMENT" + _ + "$PIPELINE_PORTFOLIO" + _ + "SUDOERS"
$PortfolioSudoersGroup = "$PIPELINE_ENVIRONMENT" + _ + "$PIPELINE_PORTFOLIO" + _ + "SUDOERS"
$ApplicationSudoersGroup = "$PIPELINE_ENVIRONMENT" + _ + "$PIPELINE_PORTFOLIO" + _ + "$PIPELINE_APP" + _ + "SUDOERS"
$LocalSudoersGroup  = "Administrators"

$PortfolioDevopsGroup = "$PIPELINE_ENVIRONMENT" + _ + "$PIPELINE_PORTFOLIO" + _ + "DEVOPS"
$ApplicationDevopsGroup = "$PIPELINE_ENVIRONMENT" + _ + "$PIPELINE_PORTFOLIO" + _ + "$PIPELINE_APP" + _ + "DEVOPS"
$LocalDevopsGroup  = "Power Users"

$Computer    = $env:computername
$Domain      = $env:userdomain

$AccessGroups =  @($GlobalAccessGroup, $PortfolioAccessGroup, $ApplicationAccessGroup)
$SudoersGroups = @($GlobalSudoersGroup, $PortfolioSudoersGroup, $ApplicationSudoersGroup)
$DevopsGroups = @($PortfolioDevopsGroup, $ApplicationDevopsGroup)


Function Add-PipelineFederationGroup($Groups, $LocalGroup) {
    Invoke-LogVerbose "Assigning Federation Groups for $localgroup"
    for $DomainGroup in $Groups {
        try {
            Invoke-LogVerbose "Adding AD Group $DomainGroup"
            ([ADSI]"WinNT://$Computer/$LocalGroup,group").psbase.Invoke("Add",([ADSI]"WinNT://$Domain/$DomainGroup").path)
            exit 0
        }
        catch [System.Exception] {
            Invoke-LogError "Failed to Add AD Group $LocalGroup!"
        exit 0 #We don't want autoscaling or anything else to fail, just log the output. 
        }
    }
}

Add-PipelineFederationGroup($AccessGroups,$LocalAccessGroup)
Add-PipelineFederationGroup($SudoersGroups,$LocalSudoersGroup)
Add-PipelineFederationGroup($DevOpsGroups,$LocalDevopsGroup)