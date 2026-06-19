# ci/check-analyses-index.ps1
# Vérifie que chaque entrée datée analyses/AAAA-MM-JJ_*.md possède une ligne
# correspondante dans analyses/INDEX.md. Échoue (exit 1) sinon.
$ErrorActionPreference = 'Stop'

$indexPath = 'analyses/INDEX.md'
if (-not (Test-Path -Path $indexPath)) {
    Write-Host "❌ $indexPath introuvable"
    exit 1
}

$indexContent = Get-Content -Path $indexPath -Raw
$fail = $false

Get-ChildItem -Path 'analyses' -Filter '*.md' |
    Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}_.*\.md$' } |
    ForEach-Object {
        if ($indexContent -notmatch [regex]::Escape($_.Name)) {
            Write-Host "❌ $($_.Name) absent de INDEX.md"
            $fail = $true
        }
    }

if ($fail) {
    Write-Host "→ Ajoute la ligne manquante dans $indexPath (cf. analyses/README.md)."
    exit 1
}

Write-Host "✅ INDEX.md à jour"
exit 0
