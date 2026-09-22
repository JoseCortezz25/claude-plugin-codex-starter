---
name: new
description: Scaffold a new Codex brand project from the private harness template, pinned to its latest GitHub release.
disable-model-invocation: true
---

# Create a new Codex brand project

You are scaffolding a new Codex brand project. Talk to the user **in Spanish** throughout.

## Rules

- Ask **one question at a time** and **wait for the answer** before asking the next one. Never batch questions, never assume answers.
- Do not create, edit, or inspect any brand files yourself. The bundled script does all the work.
- Never start working on the brand (foundations, frameworks, pieces) in this session, even if the user asks. Brand work only happens in a new session opened inside the new project folder.

## Steps

Ask, in this order, one per message:

1. **Brand name** — e.g. "HIT". Required.
2. **Project folder name** — propose a kebab-case slug of the brand name as the default (lowercase, accents removed, spaces and symbols replaced by `-`, e.g. "Sodimac Home" → `sodimac-home`). The user may accept or give another kebab-case name.
3. **Parent location** — propose the current working directory as the default, showing its **absolute path**. The user may accept or give another absolute path.
4. **Purpose** — one line describing what this project is for.

Then run the bundled script with the collected values (quote every argument):

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/new-project.sh" \
  --brand "<brand>" \
  --slug "<slug>" \
  --parent "<absolute parent path>" \
  --purpose "<purpose>"
```

Only add `--version <tag>` if the user explicitly asked for a specific harness release.

## Reporting the result

**If the script fails** (non-zero exit): explain the error to the user plainly in Spanish, using the script's message. Common cases:

- The harness has no published release yet → a maintainer must publish a GitHub release of the template first.
- No access / not logged in to `gh` → run `gh auth login` with an account that has access to the private template repo.
- git `user.name`/`user.email` not set → configure them.
- The target folder already exists and is not empty, or the parent is inside another Codex project → choose another name or location.

Then **stop**. Do not retry with other values on your own, do not fall back to cloning `main`, and do not try to create the project manually.

**If the script succeeds**: read the path from the last output line `CODEX_PROJECT_PATH=<path>`. Summarize briefly (brand, folder, harness version) and finish with this mandatory instruction, in Spanish:

> Abre una **nueva sesión de Claude Code dentro de la carpeta del proyecto**:
>
> ```bash
> cd "<path>" && claude
> ```
>
> Esto es obligatorio: las reglas, hooks y protecciones de la marca viven en el `.claude/` del proyecto y solo se cargan cuando Claude Code se inicia dentro de esa carpeta. Desde esta sesión no se trabaja la marca.

Do not continue with any further brand work after this message.
