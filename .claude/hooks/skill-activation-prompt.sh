#!/bin/bash

# Skill Activation Prompt
# Hook UserPromptSubmit — sugeruje skille na podstawie promptu użytkownika
#
# Czyta skill-rules.json i dopasowuje keywords/intentPatterns do promptu.
# Wg docs: UserPromptSubmit stdout z exit 0 trafia do Claude jako kontekst.

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
RULES_FILE="$PROJECT_DIR/.claude/skills/skill-rules.json"

# Sprawdź czy plik reguł istnieje
if [ ! -f "$RULES_FILE" ]; then
    exit 0
fi

# Sprawdź czy jq jest dostępne
if ! command -v jq &>/dev/null; then
    exit 0
fi

# Czytaj input z stdin (JSON z danymi hooka)
INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty' 2>/dev/null)

if [ -z "$PROMPT" ]; then
    exit 0
fi

# Zamień na lowercase do porównań
PROMPT_LOWER=$(echo "$PROMPT" | tr '[:upper:]' '[:lower:]')

MATCHED_SKILLS=""

# Iteruj po skillach z rules
SKILL_NAMES=$(jq -r '.skills | keys[]' "$RULES_FILE" 2>/dev/null)

for skill in $SKILL_NAMES; do
    matched=false

    # Sprawdź keywords (while read zachowuje spacje w wielowyrazowych keywords)
    while IFS= read -r kw; do
        [ -z "$kw" ] && continue
        kw_lower=$(echo "$kw" | tr '[:upper:]' '[:lower:]')
        if echo "$PROMPT_LOWER" | grep -qF "$kw_lower"; then
            matched=true
            break
        fi
    done <<EOF
$(jq -r ".skills[\"$skill\"].promptTriggers.keywords // [] | .[]" "$RULES_FILE" 2>/dev/null)
EOF

    # Sprawdź intentPatterns (tylko jeśli keyword nie dopasował)
    if [ "$matched" = false ]; then
        while IFS= read -r pattern; do
            [ -z "$pattern" ] && continue
            if echo "$PROMPT_LOWER" | grep -qiE "$pattern" 2>/dev/null; then
                matched=true
                break
            fi
        done <<EOF
$(jq -r ".skills[\"$skill\"].promptTriggers.intentPatterns // [] | .[]" "$RULES_FILE" 2>/dev/null)
EOF
    fi

    if [ "$matched" = true ]; then
        MATCHED_SKILLS="$MATCHED_SKILLS $skill"
    fi
done

# Wypisz dopasowane skille na stdout (UserPromptSubmit: stdout z exit 0 → kontekst dla Claude)
if [ -n "$MATCHED_SKILLS" ]; then
    SKILL_LIST=""
    for skill in $MATCHED_SKILLS; do
        SKILL_LIST="${SKILL_LIST}\n  → ${skill}"
    done

    printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n🎯 SKILL ACTIVATION CHECK\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n📚 RECOMMENDED SKILLS:%b\n\nACTION: Use Skill tool BEFORE responding\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n' "$SKILL_LIST"
fi

exit 0
