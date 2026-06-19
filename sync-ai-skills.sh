#!/usr/bin/env bash
# Sync shared AI assets: skills (ai/skills/**) and project context (Claude.md)
# into the locations consumed by GitHub Copilot and Claude Code.
#
# Single sources of truth:
#   - ai/skills/<category>/<skill>/SKILL.md  (the skills)
#   - Claude.md                              (the project context / rules)
#
# This script:
#   1. Copies each skill folder (flattened by skill name) into:
#        - .github/skills/<skill>/   (GitHub Copilot)
#        - .claude/skills/<skill>/   (Claude Code)
#   2. Mirrors Claude.md into .github/copilot-instructions.md so BOTH assistants
#      share the exact same project context (Copilot auto-loads that file).
#
# Uses real file copies (no symlinks) for cross-platform portability.
# Run after editing any skill under ai/skills/, OR after editing Claude.md.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src_root="$repo/ai/skills"

if [ ! -d "$src_root" ]; then
  echo "Source skills directory not found: $src_root" >&2
  exit 1
fi

mapfile -t skill_files < <(find "$src_root" -type f -name 'SKILL.md')
if [ "${#skill_files[@]}" -eq 0 ]; then
  echo "No SKILL.md found under $src_root" >&2
  exit 1
fi

for target in "$repo/.github/skills" "$repo/.claude/skills"; do
  rm -rf "$target"
  mkdir -p "$target"
  for skill_file in "${skill_files[@]}"; do
    skill_dir="$(dirname "$skill_file")"
    skill_name="$(basename "$skill_dir")"
    cp -R "$skill_dir" "$target/$skill_name"
    echo "  $skill_name -> $target/$skill_name"
  done
  echo "Synced ${#skill_files[@]} skill(s) into $target"
done

# --- Project context: mirror Claude.md -> .github/copilot-instructions.md ---
context_src="$repo/Claude.md"
copilot_dst="$repo/.github/copilot-instructions.md"
if [ -f "$context_src" ]; then
  mkdir -p "$(dirname "$copilot_dst")"
  {
    printf '%s\n' '<!--'
    printf '%s\n' '  GENERATED FILE - DO NOT EDIT.'
    printf '%s\n' '  Source of truth: Claude.md (repo root). Regenerate with ./sync-ai-skills.sh.'
    printf '%s\n' '  Shared project context for GitHub Copilot, mirrored verbatim from Claude.md.'
    printf '%s\n\n' '-->'
    cat "$context_src"
  } > "$copilot_dst"
  echo "Mirrored Claude.md -> $copilot_dst"
else
  echo "Claude.md not found at $context_src - skipped copilot-instructions mirror." >&2
fi
