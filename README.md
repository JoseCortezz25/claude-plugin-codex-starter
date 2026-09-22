# codex-brand — plugin de Claude Code para proyectos de marca Codex

Plugin (y marketplace privado) para crear proyectos de marca **Codex** a partir de la plantilla del
arnés (`JoseCortezz25/delivery-system-starter`, repo privado) y proteger esos proyectos para que no se
operen desde una carpeta padre.

- `/codex-brand:new` — crea un proyecto de marca nuevo, fijado a una **release** publicada de la plantilla.
- Hooks — detectan si la sesión está dentro de un proyecto Codex o en una carpeta padre, y bloquean
  escrituras en un proyecto de marca desde una sesión que no se abrió en su raíz.

> Uso interno de la organización. Tanto este repo como la plantilla son privados.

## Requisitos

- **Claude Code** instalado y autenticado.
- **git** con `user.name` y `user.email` configurados (se usan para el commit inicial del proyecto).
- **GitHub CLI (`gh`)** con sesión iniciada (`gh auth login`) y acceso a **ambos** repos privados:
  este plugin y la plantilla del arnés.
- **jq**.

## Instalación (miembros de la organización)

```shell
/plugin marketplace add JoseCortezz25/claude-plugin-codex-starter
/plugin install codex-brand@codex-brand-marketplace
```

El atajo `owner/repo` clona por SSH. **Se recomienda SSH** (llave cargada en `ssh-agent` y GitHub en
`known_hosts`): las actualizaciones automáticas en segundo plano de repos privados no usan
credential helpers, así que por HTTPS pueden fallar en silencio.

Si no tienes una llave SSH registrada en GitHub, instala por HTTPS:

```shell
gh auth setup-git
/plugin marketplace add https://github.com/JoseCortezz25/claude-plugin-codex-starter.git
```

Esto solo afecta a la instalación del plugin: `/codex-brand:new` clona la plantilla siempre por
HTTPS con tu sesión de `gh`, sin depender de SSH.

### Opcional: habilitarlo para todo un equipo

En el `.claude/settings.json` del repo del equipo:

```json
{
  "extraKnownMarketplaces": {
    "codex-brand-marketplace": {
      "source": {
        "source": "github",
        "repo": "JoseCortezz25/claude-plugin-codex-starter"
      }
    }
  },
  "enabledPlugins": {
    "codex-brand@codex-brand-marketplace": true
  }
}
```

## Uso

En una sesión de Claude Code abierta en la carpeta donde quieres crear el proyecto:

```shell
/codex-brand:new
```

El asistente pregunta, una por una: nombre de la marca, nombre de la carpeta (propone un slug kebab-case),
ubicación padre (propone el directorio actual) y propósito. Luego ejecuta
`scripts/new-project.sh`, que:

1. Verifica `git`, `gh`, `jq`, la sesión de `gh`, el acceso a la plantilla y tu identidad de git.
2. Resuelve la versión: `--version <tag>` o la **última release** de la plantilla. Si no hay release, falla (nunca usa `main`).
3. Rechaza la operación si la carpeta destino existe y no está vacía, o si la ubicación padre está dentro de otro proyecto Codex.
4. Clona la release por HTTPS (con la sesión de `gh`), elimina su historial, hace `git init`, escribe `codex-lock.json` y crea el commit inicial.

Al terminar, **abre una sesión nueva dentro del proyecto**:

```bash
cd "<ruta-del-proyecto>" && claude
```

La plantilla se puede cambiar con la variable de entorno `CODEX_TEMPLATE_REPO` (formato `owner/repo`).

## `codex-lock.json`

Marca la raíz de un proyecto Codex y registra de dónde salió:

```json
{
  "schemaVersion": 1,
  "harness": { "name": "codex", "version": "v1.0.0", "repo": "https://github.com/<repo>", "commit": "<sha>" },
  "brand": { "name": "HIT", "codexVersion": "0.1.0" },
  "project": { "name": "hit", "purpose": "…", "createdAt": "2026-01-01T00:00:00Z" },
  "createdWith": { "plugin": "codex-brand", "pluginVersion": "0.1.0" }
}
```

| Campo | Significado |
|---|---|
| `schemaVersion` | Versión del formato de este archivo. |
| `harness.version` / `commit` | Release (tag) de la plantilla usada y su commit exacto. |
| `harness.repo` | Repo de la plantilla. |
| `brand.name` | Nombre de la marca. `brand.codexVersion`: versión del formato de marca Codex. |
| `project.*` | Nombre de carpeta, propósito y fecha de creación (UTC, ISO-8601). |
| `createdWith` | Plugin y versión que lo crearon (leídos de `plugin.json`). |

## Regla: nunca operar un proyecto desde la carpeta padre

Las reglas y hooks de cada marca viven en el `.claude/` del proyecto y **solo se cargan si Claude Code se
inicia dentro de esa carpeta**. Operarlo desde una carpeta padre deja la marca sin sus protecciones.
El plugin lo refuerza así:

- **SessionStart**: si la sesión está en una carpeta que contiene proyectos Codex (hasta 2 niveles), le indica
  a Claude que no los opere desde ahí y que te pida `cd <ruta> && claude`. Si la sesión está dentro de un
  proyecto, agrega una línea de contexto con la marca y la versión del arnés.
- **PreToolUse (Write/Edit/NotebookEdit)**: si el archivo a escribir pertenece a un proyecto Codex cuya raíz no
  es la raíz de la sesión actual, la escritura se **deniega** con la instrucción de abrir una sesión allí.

## Versiones

Las versiones disponibles son las **GitHub releases** de la plantilla. Para que una versión esté disponible,
publica una release en el repo de la plantilla. Mientras no exista ninguna, `/codex-brand:new` falla con un
mensaje claro.

## Renombrar el plugin

El nombre `codex-brand` aparece solo en `.claude-plugin/plugin.json` y en la entrada de
`.claude-plugin/marketplace.json` (los scripts lo leen de `plugin.json`). Cambiarlo cambia el namespace del
comando (`/<nuevo-nombre>:new`) y el identificador de instalación, así que cada usuario debe
**desinstalar y reinstalar** el plugin.
