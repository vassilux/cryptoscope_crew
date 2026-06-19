<#
.SYNOPSIS
  Sync shared AI assets: skills (ai/skills/**) and project context (Claude.md)
  into the locations consumed by GitHub Copilot and Claude Code.

.DESCRIPTION
  Single sources of truth:
    - ai/skills/<category>/<skill>/SKILL.md  (the skills)
    - Claude.md                              (the project context / rules)

  This script:
    1. Copies each skill folder (flattened by skill name) into:
         - .github/skills/<skill>/   (GitHub Copilot)
         - .claude/skills/<skill>/   (Claude Code)
    2. Mirrors Claude.md into .github/copilot-instructions.md so BOTH assistants
       share the exact same project context (Copilot auto-loads that file).

  Uses real file copies (no symlinks) for Windows 11 / cross-platform portability.
  Run it after adding, renaming, or editing any skill under ai/skills/, OR after
  editing Claude.md.

.EXAMPLE
  pwsh ./sync-ai-skills.ps1
#>
$ErrorActionPreference = 'Stop'

$repo    = $PSScriptRoot
$srcRoot = Join-Path $repo 'ai\skills'
$targets = @(
    (Join-Path $repo '.github\skills'),
    (Join-Path $repo '.claude\skills')
)

if (-not (Test-Path $srcRoot)) {
    throw "Source skills directory not found: $srcRoot"
}

# Safely remove a target path that may be (or may contain) directory symlinks
# / junctions (reparse points) without following them into their targets.
function Remove-PathSafe {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }

    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        # The path itself is a symlink/junction: remove the link only.
        [System.IO.Directory]::Delete($Path, $false)
        return
    }

    # Real directory: delete any nested reparse points first (deepest last),
    # so Remove-Item never recurses into a link target.
    Get-ChildItem -LiteralPath $Path -Recurse -Force |
        Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object {
            if ($_.PSIsContainer) { [System.IO.Directory]::Delete($_.FullName, $false) }
            else                  { [System.IO.File]::Delete($_.FullName) }
        }

    Remove-Item -LiteralPath $Path -Recurse -Force
}

# Discover all skills (folders containing a SKILL.md, at any depth)
$skillFiles = Get-ChildItem -Path $srcRoot -Recurse -Filter 'SKILL.md' -File
if ($skillFiles.Count -eq 0) {
    throw "No SKILL.md found under $srcRoot"
}

foreach ($target in $targets) {
    Remove-PathSafe -Path $target
    New-Item -ItemType Directory -Path $target -Force | Out-Null

    foreach ($skillFile in $skillFiles) {
        $skillDir  = $skillFile.Directory
        $skillName = $skillDir.Name
        $dest      = Join-Path $target $skillName
        Copy-Item -Path $skillDir.FullName -Destination $dest -Recurse -Force
        Write-Host ("  {0} -> {1}" -f $skillName, (Resolve-Path $dest))
    }
    Write-Host ("Synced {0} skill(s) into {1}" -f $skillFiles.Count, $target) -ForegroundColor Green
}

# --- Project context: mirror Claude.md -> .github/copilot-instructions.md ---
$contextSrc = Join-Path $repo 'Claude.md'
$copilotDst = Join-Path $repo '.github\copilot-instructions.md'
if (Test-Path $contextSrc) {
    $banner = @"
<!--
  GENERATED FILE - DO NOT EDIT.
  Source of truth: Claude.md (repo root). Regenerate with ./sync-ai-skills.ps1.
  Shared project context for GitHub Copilot, mirrored verbatim from Claude.md.
-->

"@
    New-Item -ItemType Directory -Path (Split-Path $copilotDst) -Force | Out-Null
    $body = Get-Content -LiteralPath $contextSrc -Raw
    Set-Content -LiteralPath $copilotDst -Value ($banner + $body) -Encoding UTF8
    Write-Host ("Mirrored Claude.md -> {0}" -f (Resolve-Path $copilotDst)) -ForegroundColor Green
} else {
    Write-Warning "Claude.md not found at $contextSrc - skipped copilot-instructions mirror."
}
