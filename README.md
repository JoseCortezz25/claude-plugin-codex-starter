# codex-brand — plugin de Claude Code para proyectos de marca Codex

Plugin (y marketplace privado) para crear proyectos de marca **Codex** a partir de la plantilla del
arnés (`JoseCortezz25/delivery-system-starter`, repo privado) y proteger esos proyectos para que no se
operen desde una carpeta padre.

- `/codex-brand:new` — crea un proyecto de marca nuevo, fijado a una **release** publicada de la plantilla.
- `/codex-brand:report-bug` y `/codex-brand:feedback` — envían un bug o una sugerencia al equipo Codex.
- Hooks — detectan si la sesión está dentro de un proyecto Codex o en una carpeta padre, y bloquean
  escrituras en un proyecto de marca desde una sesión que no se abrió en su raíz.

> Uso interno de la organización. Tanto este repo como la plantilla son privados.

## Paso a paso

**1. Prepara tu equipo (una sola vez).**
Pide acceso a los dos repos privados: `JoseCortezz25/claude-plugin-codex-starter` y
`JoseCortezz25/delivery-system-starter`. Después configura git en la terminal:

```bash
git config --global user.name "Tu Nombre"
git config --global user.email "tu@correo.com"
brew install jq
```

Para autenticarte con GitHub hay dos opciones:

- **Con GitHub CLI** (recomendado): `brew install gh`, luego `gh auth login` y `gh auth setup-git`.
- **Sin GitHub CLI**: corre una vez
  `git clone https://github.com/JoseCortezz25/delivery-system-starter.git` e ingresa tu usuario de
  GitHub y un *personal access token* como contraseña. Git lo guarda y después puedes borrar esa
  carpeta.

**2. Instala el plugin (una sola vez).** En Claude Code:

```
/plugin marketplace add https://github.com/JoseCortezz25/claude-plugin-codex-starter.git
/plugin install codex-brand@codex-brand-marketplace
```

Reinicia Claude Code.

Activa la actualización automática (recomendado, una sola vez): `/plugin` → pestaña **Marketplaces** →
`codex-brand-marketplace` → **Enable auto-update**. Sin esto, actualiza a mano cuando haya una versión
nueva:

```bash
claude plugin update codex-brand@codex-brand-marketplace
```

> Actualizar el plugin no modifica los proyectos que ya creaste: solo cambia cómo se crean los nuevos.

**3. Crea el proyecto.** Abre Claude Code en la carpeta donde quieres guardarlo (por ejemplo
`~/Proyectos`), escribe `/codex-brand:new` y responde las preguntas: marca, nombre de carpeta,
ubicación y propósito.

**4. Abre el proyecto (obligatorio).** Sal de esa sesión y abre Claude **dentro** de la carpeta nueva:

```bash
cd ~/Proyectos/nombre-del-proyecto && claude
```

> ⚠️ Nunca trabajes una marca desde una carpeta superior: sus reglas y protecciones solo se activan
> dentro de la carpeta del proyecto.

**5. Configura la marca y produce piezas.** Claude te guía en dos etapas:
- **Setup:** te pide todo lo que tengas de la marca (brandbook, logos, fuentes, colores, tono,
  referencias) y lo organiza. Cuando digas "listo, no tengo más", hace una pieza de prueba.
- **Ejecución:** con la marca aprobada, le pides las piezas que necesites.

### Problemas comunes

| Mensaje o problema | Solución |
|---|---|
| `the harness has no published release yet` | La plantilla no tiene una versión publicada. Avísale al dueño del repo. |
| `cannot access ...` o `clone ... failed` | Tu cuenta no tiene acceso a la plantilla, o git no tiene credenciales guardadas. Revisa el paso 1. |
| Falla `/plugin marketplace add` | Corre `gh auth setup-git`, o guarda credenciales con un `git clone` como en el paso 1, y repite. |
| No aparece `/codex-brand:new` | Reinicia Claude Code y revisa con `/plugin` que esté instalado. |
| Claude no te deja editar la marca | Estás en una carpeta superior. Entra a la carpeta del proyecto y abre `claude` ahí. |

## Requisitos

- **Claude Code** instalado y autenticado.
- **git** con `user.name` y `user.email` configurados (se usan para el commit inicial del proyecto).
- Acceso a **ambos** repos privados en GitHub: este plugin y la plantilla del arnés.
- **GitHub CLI (`gh`)** con sesión iniciada (`gh auth login`) — **opcional**. Si no está instalado o
  no tiene sesión, el plugin usa **git normal** con tus credenciales: la primera vez corre
  `git clone https://github.com/JoseCortezz25/delivery-system-starter.git` en una terminal para que git
  guarde tu acceso (usuario de GitHub + *personal access token* como contraseña), o usa SSH definiendo
  `CODEX_TEMPLATE_URL=git@github.com:JoseCortezz25/delivery-system-starter.git`.
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

1. Verifica `git`, `jq`, tu identidad de git y el acceso a la plantilla. Usa `gh` si está instalado y con sesión; si no, git normal.
2. Resuelve la versión: `--version <tag>` o la **última release** de la plantilla (sin `gh`, el tag semver más alto, que es el que crea cada release). Si no hay release, falla (nunca usa `main`).
3. Rechaza la operación si la carpeta destino existe y no está vacía, o si la ubicación padre está dentro de otro proyecto Codex.
4. Clona la release (con `gh`: por HTTPS con su sesión; sin `gh`: con la URL y las credenciales de git), elimina su historial, hace `git init`, escribe `codex-lock.json` y crea el commit inicial.

Al terminar, **abre una sesión nueva dentro del proyecto**:

```bash
cd "<ruta-del-proyecto>" && claude
```

La plantilla se puede cambiar con la variable de entorno `CODEX_TEMPLATE_REPO` (formato `owner/repo`).

## Reportar bugs y enviar feedback

- `/codex-brand:report-bug` — reporta un error o una fricción mientras trabajas una marca.
- `/codex-brand:feedback` — propone una mejora al flujo de Codex.

Claude toma el contexto de la sesión (marca, proyecto, framework, pieza, archivos relacionados) y los
datos técnicos (tu nombre y correo de git, sistema operativo, versiones de Claude Code, del plugin y del
arnés, modelo, fecha), te pregunta solo lo que falta, **una pregunta a la vez**, y te muestra una vista
previa. Solo envía si confirmas. El reporte llega al canal del equipo como un archivo HTML
autocontenido, generado por `scripts/send_report.py` (Python 3, sin dependencias).

- **Destino:** el webhook del canal se lee de `config/report.json` (`webhookUrl`); se puede reemplazar con la
  variable de entorno `CODEX_REPORT_WEBHOOK_URL`.
- **Si no se puede enviar** (sin red, proxy, webhook inválido), el HTML queda guardado en
  `~/.codex-ocx/reports-pending/` y se reintenta automáticamente la próxima vez que envíes un reporte o
  feedback. Si tu red usa proxy, debe permitir `*.powerplatform.com`.
- Nunca se escriben archivos del reporte dentro de tu proyecto; se usa una carpeta temporal.

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
| `brand.name` / `codexVersion` | Nombre de la marca y su propia versión Codex (semver, empieza en `0.1.0`; sube a medida que se aprueban foundations y frameworks). |
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
