# Installation locale de DISCOVERY (databricks-ai-studio) sur un PC Windows
# Usage (PowerShell) :  powershell -ExecutionPolicy Bypass -File .\installer_discovery_local.ps1
# Aucun secret dans ce script. Execution avec VOTRE identite Databricks (droits Unity Catalog personnels).
param(
  [string]$Dossier   = "$HOME\discovery",
  [string]$HostDbx   = "https://adb-859050144319207.7.azuredatabricks.net",
  [string]$Profil    = "discovery",
  [switch]$SansTests,
  [switch]$Lancer
)
$ErrorActionPreference = "Stop"
$Source = "/Users/phsi10251@commun.ad.sncf.fr/migration_ai/apps/databricks-ai-studio"
function Etape($t) { Write-Host "`n=== $t ===" -ForegroundColor Magenta }

Etape "1/6 Verification de Python (3.11 ou plus)"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { throw "Python introuvable. Installez Python 3.11+ (Centre logiciel SNCF ou python.org) puis relancez." }
$v = (& python -c "import sys;print('%d.%d' % sys.version_info[:2])")
if ([version]$v -lt [version]"3.11") { throw "Python $v detecte : 3.11 ou plus requis." }
Write-Host "Python $v OK"

Etape "2/6 Verification de la CLI Databricks"
if (-not (Get-Command databricks -ErrorAction SilentlyContinue)) {
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install --id Databricks.DatabricksCLI -e --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
  }
  if (-not (Get-Command databricks -ErrorAction SilentlyContinue)) {
    throw "CLI Databricks introuvable. Installez-la : https://learn.microsoft.com/azure/databricks/dev-tools/cli/install"
  }
}
databricks --version

Etape "3/6 Connexion a l'espace Databricks (navigateur)"
$ok = $false
# Meme verification que le SDK de l'App : jeton OAuth du profil fourni par la CLI
try { databricks auth token --profile $Profil 2>$null | Out-Null; $ok = ($LASTEXITCODE -eq 0) } catch { $ok = $false }
if (-not $ok) { databricks auth login --host $HostDbx --profile $Profil }
databricks current-user me --profile $Profil --output json | python -c "import sys,json;print('Connecte : '+json.load(sys.stdin)['userName'])"

Etape "4/6 Recuperation du code depuis l'espace de travail"
if (Test-Path $Dossier) { Write-Host "Dossier existant $Dossier : mise a jour (fichiers ecrases)" }
databricks workspace export-dir $Source $Dossier --overwrite --profile $Profil
if ($LASTEXITCODE -ne 0) { throw "Export du code impossible (droits sur $Source ?)." }
Set-Location $Dossier

Etape "5/6 Environnement Python et dependances"
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest
if ($LASTEXITCODE -ne 0) { throw "Installation des paquets impossible (proxy SNCF ? voir commentaire ci-dessous)." }
# Si pip echoue sur le reseau SNCF : definir le proxy, ex. $env:HTTPS_PROXY="http://<proxy>:<port>" puis relancer.

# Lanceur : variables de app.yaml (hors secrets), identite du developpeur
@"
# CLI Databricks : PATH rafraichi + chemin explicite pour le SDK (barres / obligatoires sous Windows)
`$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
`$cli = Get-Command databricks -ErrorAction SilentlyContinue
if (-not `$cli) { throw "CLI Databricks introuvable dans le PATH : relancez installer_discovery_local.ps1" }
`$env:DATABRICKS_CLI_PATH = `$cli.Source -replace '\\','/'
# Jeton du profil : reconnexion par le navigateur s'il est absent ou expire
try { databricks auth token --profile $Profil 2>`$null | Out-Null; `$ok = (`$LASTEXITCODE -eq 0) } catch { `$ok = `$false }
if (-not `$ok) { databricks auth login --host $HostDbx --profile $Profil }
`$env:DATABRICKS_CONFIG_PROFILE = "$Profil"
`$env:DATABRICKS_WAREHOUSE_ID   = "d0642494ed2912f0"
`$env:AI_STUDIO_DEFAULT_MODEL   = "databricks-claude-sonnet-4-6"
`$env:AI_STUDIO_CATALOG = "dataops_dev"; `$env:AI_STUDIO_SCHEMA = "ai_studio"
`$env:AI_STUDIO_DATA_CATALOG = "dataops_dev"; `$env:AI_STUDIO_DATA_SCHEMA = "ai_studio"; `$env:AI_STUDIO_DATA_PREFIX = "data_"
`$env:AI_STUDIO_MAX_ROWS = "200"; `$env:AI_STUDIO_HAKIM_ENABLED = "true"
`$env:AI_STUDIO_TOOL_ADMINS = "phsi10251@commun.ad.sncf.fr"; `$env:AI_STUDIO_TEAM_ADMINS = "phsi10251@commun.ad.sncf.fr"
`$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
Remove-Item Env:DATABRICKS_APP_NAME -ErrorAction SilentlyContinue
Set-Location "$Dossier"
& .\.venv\Scripts\python.exe -m streamlit run app.py
"@ | Set-Content -Encoding ASCII lancer_discovery.ps1

Etape "6/6 Tests unitaires"
if (-not $SansTests) {
  $env:PYTHONDONTWRITEBYTECODE = "1"
  & .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests
  if ($LASTEXITCODE -ne 0) { throw "Tests en echec : installation incomplete." }
}

Write-Host "`nInstallation terminee dans $Dossier" -ForegroundColor Green
Write-Host "Lancer DISCOVERY : powershell -ExecutionPolicy Bypass -File `"$Dossier\lancer_discovery.ps1`"  -> http://localhost:8501"
if ($Lancer) { & "$Dossier\lancer_discovery.ps1" }
