param([switch]$Supprimer)

# Cree (ou supprime) la tache planifiee 'Doctrine MCP - mises a jour' :
# tous les jours a 12h30, sous le compte de l'utilisateur connecte ; si le PC etait eteint,
# la tache demarre des qu'il est disponible.
$nom = 'Doctrine MCP - mises a jour'

if ($Supprimer) {
    Unregister-ScheduledTask -TaskName $nom -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tache planifiee supprimee."
    exit 0
}

$dossier = $PSScriptRoot
$script = Join-Path $dossier 'mise_a_jour_tout.bat'
if (-not (Test-Path $script)) {
    Write-Host "mise_a_jour_tout.bat est introuvable dans $dossier"
    exit 1
}

try {
    $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c ""' + $script + '" auto"') -WorkingDirectory $dossier
    $declencheur = New-ScheduledTaskTrigger -Daily -At '12:30'
    $reglages = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $nom -Action $action -Trigger $declencheur -Settings $reglages -Description 'Met a jour BOFiP (le lundi), les codes Legifrance et le BOSS pour le serveur MCP Doctrine fiscale.' -Force | Out-Null
    $info = Get-ScheduledTask -TaskName $nom | Get-ScheduledTaskInfo
    Write-Host "Tache planifiee creee : $nom"
    Write-Host "Prochain lancement : $($info.NextRunTime)"
    Write-Host "Journal : $dossier\journal_mises_a_jour.log"
} catch {
    Write-Host "Echec de la creation de la tache : $($_.Exception.Message)"
    exit 1
}
