import type { AppLanguage } from "@/api/types";

/**
 * Typed bilingual message catalogue (AD-1). Every user-visible chrome string
 * in scope resolves through this catalogue via `translate()` / the `t`
 * helper exposed by `useAppLanguage()`. The `es` locale is strict neutral
 * Spanish (no voseo, no regionalisms — see `forbidden.json`); parity between
 * `es` and `en` is enforced at compile time by `MessageKey` and at runtime by
 * the catalogue guard (`__tests__/catalogueGuard.test.ts`).
 */

export type TParams = Record<string, string | number>;
export type TFunction = (key: MessageKey, params?: TParams) => string;

export const messages = {
  es: {
    "document.title": "Demiurgos — Wiki",

    "assistant.session.defaultTitle": "Nueva sesión",

    "common.save": "Guardar",
    "common.saving": "Guardando…",
    "common.cancel": "Cancelar",
    "common.continue": "Continuar",
    "common.creating": "Creando…",

    "nav.links.tallerHerramientas": "Taller de Herramientas",
    "nav.links.tallerIdeas": "Taller de Ideas",
    "nav.links.tallerMundo": "Taller de Mundo",
    "nav.soon": "Próximamente",
    "nav.theme.dark": "Tema: oscuro",
    "nav.theme.light": "Tema: claro",
    "nav.toggleTheme": "Cambiar tema",
    "nav.homeAria": "Demiurgos — ir al inicio",
    "nav.mainAria": "Navegación principal",
    "nav.mobileAria": "Navegación móvil",
    "nav.profileAria": "Perfil",
    "nav.profile.openFull": "Perfil completo",
    "nav.session.title": "Sesión de edición",
    "nav.session.mode.credentials": "Credenciales",
    "nav.session.mode.local": "Local",
    "nav.session.checking": "Comprobando sesión...",
    "nav.session.active": "Sesión activa",
    "nav.session.closing": "Cerrando...",
    "nav.session.logout": "Cerrar sesión",
    "nav.session.none": "No hay una sesión de cuenta activa.",
    "nav.session.local.checking": "Comprobando sesión local...",
    "nav.session.local.active": "Sesión local activa",
    "nav.session.local.logout": "Cerrar sesión local",
    "nav.session.local.notStarted": "Sesión local no iniciada.",
    "nav.session.local.start": "Iniciar sesión local",
    "nav.session.local.starting": "Iniciando...",
    "nav.session.local.disabled":
      "Autenticación local desactivada. Activa DEMIURGOS_AUTH_MODE=local-dev para probar la edición.",
    "nav.session.error.fetch": "No se pudo consultar la sesión",
    "nav.session.error.update": "No se pudo actualizar la sesión local",
    "nav.system.error.operation": "No se pudo completar la operación",
    "nav.system.serverDown":
      "El servidor no respondió. Arráncalo de nuevo o recarga la página.",
    "nav.system.restart": "Reiniciar Demiurgos",
    "nav.system.shutdown": "Apagar Demiurgos",
    "nav.system.restarting": "Reiniciando Demiurgos…",
    "nav.system.shuttingDown": "Apagando Demiurgos…",
    "nav.system.off": "Demiurgos se apagó",
    "nav.system.confirm.title.restart": "Reiniciar Demiurgos",
    "nav.system.confirm.title.shutdown": "Apagar Demiurgos",
    "nav.system.confirm.title.logout": "Cerrar sesión",
    "nav.system.confirm.message.restart":
      "La conexión se cortará y la página quedará en blanco por unos segundos. Cuando el servidor vuelva, la página se recargará automáticamente; tu sesión se conserva.",
    "nav.system.confirm.message.shutdown":
      "El servidor se detendrá y el bot dejará de recibir ideas. Para volver a usarlo, arráncalo de nuevo; tu sesión se conserva.",
    "nav.system.confirm.message.logout":
      "Cerrar la sesión deja el servidor y el bot corriendo; puedes volver a entrar cuando quieras.",
    "nav.system.confirm.confirm.restart": "Reiniciar",
    "nav.system.confirm.confirm.shutdown": "Apagar",
    "nav.system.confirm.confirm.logout": "Cerrar sesión",
    "nav.system.transition.restarting":
      "El servidor se está reiniciando. La página se recargará automáticamente cuando vuelva; tu sesión se conserva.",
    "nav.system.transition.shuttingDown":
      "El servidor se está apagando. Cuando termine, la pantalla lo confirmará; tu sesión se conserva.",
    "nav.system.transition.off":
      "La aplicación se detuvo por completo. Arráncalo de nuevo para volver a usarla; tu sesión se conserva.",
    "nav.world.confirm.title": "Cambiar mundo activo",
    "nav.world.confirm.message": "¿Quieres cambiar el mundo activo a «{name}»?",
    "nav.world.confirm.confirm": "Cambiar",

    "onboarding.title": "Bienvenida a Demiurgos",
    "onboarding.intro":
      "Configuración inicial para dejar la instalación operativa. Puedes retomar cada capacidad después desde el Perfil.",
    "onboarding.loadError": "No se pudo consultar el estado de la instalación.",
    "onboarding.step1.title": "Paso 1: idioma, región y zona horaria",
    "onboarding.world.title": "Crea tu mundo",
    "onboarding.world.intro":
      "Se crea un árbol canónico en minúsculas (lore, personajes). El mundo es el último paso operativo para entrar al Taller de Mundo.",
    "onboarding.world.name": "Nombre del mundo",
    "onboarding.world.namePlaceholder": "mi-mundo",
    "onboarding.world.loreSkeleton":
      "Incluir la estructura Lore recomendada (carpetas vacías)",
    "onboarding.world.create": "Crear mundo",
    "onboarding.pending.title": "Lo que queda pendiente",
    "onboarding.pending.aria": "Capacidades pendientes",
    "onboarding.pending.badge": "Pendiente",
    "onboarding.pending.none": "No hay capacidades pendientes.",
    "onboarding.remote.ai.title": "Asistente de Demiurgos (texto y visión)",
    "onboarding.remote.ai.desc":
      "Requiere un modelo local o remoto validado. Se retoma desde el Perfil.",
    "onboarding.remote.telegram.title": "Telegram",
    "onboarding.remote.telegram.desc":
      "Requiere conexión y una cuenta configurada. Se retoma desde el Perfil.",
    "onboarding.remote.backup.title": "Respaldo y restauración",
    "onboarding.remote.backup.desc":
      "Requiere conexión y consentimiento. Se retoma desde el Perfil.",
    "onboarding.account.title": "Crea tu cuenta",
    "onboarding.account.intro":
      "La cuenta protege tu instalación. La contraseña es opcional: sin ella alcanza con el botón Entrar para ingresar.",
    "onboarding.account.username": "Usuario",
    "onboarding.account.usernamePlaceholder": "tu-usuario",
    "onboarding.account.password": "Contraseña (opcional)",
    "onboarding.account.passwordPlaceholder":
      "Déjalo vacío para entrar sin contraseña",
    "onboarding.account.wordsIntro":
      "Al crear la cuenta se generan tus palabras claves: son tu única forma de recuperarla si olvidas la contraseña. Se muestran una sola vez y no se pueden volver a ver.",
    "onboarding.account.createError": "No se pudo crear la cuenta",
    "onboarding.account.create": "Crear cuenta",
    "onboarding.words.title": "Tus palabras claves",
    "onboarding.words.intro":
      "Guárdalas en un lugar seguro, fuera del navegador. Solo se muestran una vez: si las pierdes y olvidas la contraseña, la cuenta queda bloqueada para siempre.",
    "onboarding.words.confirm": "Guardé mis palabras",

    "locale.form.intro":
      "Cada lenguaje se configura de forma independiente; la región solo sugiere valores y nunca se aplica en silencio.",
    "locale.ui": "Idioma de la interfaz",
    "locale.conversation": "Idioma de conversación (asistente)",
    "locale.content": "Idioma de contenido (prosa del mundo)",
    "locale.inherit": "Igual que la interfaz",
    "locale.region":
      "Región (opcional; sugiere valores, nunca impone dialecto)",
    "locale.regionPlaceholder": "AR, MX, US…",
    "locale.regionExplicit": "Confirmo la región de forma explícita (override)",
    "locale.timezone": "Zona horaria (los timestamps se guardan en UTC)",

    "profile.locale.checking": "Comprobando configuración…",
    "profile.locale.loadError":
      "No se pudieron cargar los estados de configuración.",
    "profile.locale.title": "Idioma, región y zona horaria",
    "profile.locale.stateLabel": "Estado: {label}",

    "profile.title": "Perfil",
    "profile.section.cuenta": "Cuenta",
    "profile.section.respaldo": "Respaldo",
    "profile.section.preferencias": "Preferencias",
    "profile.section.conexiones": "Conexiones",
    "profile.section.mundos": "Mundos",

    "profile.cuenta.checkingVault": "Comprobando la bóveda…",
    "profile.cuenta.loadError": "No se pudo cargar el estado de la bóveda.",
    "profile.cuenta.session": "Sesión",
    "profile.cuenta.sessionActive": "Activa",
    "profile.cuenta.sessionOff": "Apagada",
    "profile.cuenta.account": "Cuenta",
    "profile.cuenta.passwordSet": "contraseña definida",
    "profile.cuenta.noPassword": "sin contraseña",
    "profile.cuenta.forcedBy": "Forzada por",
    "profile.cuenta.recoveryWords": "Palabras claves",
    "profile.cuenta.wordsUnlocked": "Desbloqueadas esta sesión",
    "profile.cuenta.wordsLocked": "Bloqueadas",
    "profile.cuenta.reauth": "Reingreso",
    "profile.cuenta.today": "hoy",
    "profile.cuenta.inDaysOne": "en 1 día",
    "profile.cuenta.inDaysMany": "en {days} días",
    "profile.cuenta.noActiveSession":
      "No hay una sesión de cuenta activa. Inicia sesión para editar y configurar el perfil.",
    "profile.cuenta.localChecking": "Comprobando sesión local…",
    "profile.cuenta.localSession": "Sesión local",
    "profile.cuenta.localNotStarted":
      "Sesión local no iniciada. Iníciala desde el menú de tu perfil para editar y configurar el perfil.",
    "profile.cuenta.localDisabled":
      "Autenticación local desactivada. Activa DEMIURGOS_AUTH_MODE=local-dev en .env para probar la edición.",
    "profile.cuenta.manageCredentials": "Gestionar credenciales",
    "profile.cuenta.credentialsAria": "Gestión de credenciales",
    "profile.cuenta.credentialsIntro":
      "Tus palabras claves son la llave de propiedad de la cuenta: la primera acción que las pida las desbloquea para esta sesión y se recuerdan hasta cerrar sesión, sin guardarse en el navegador.",
    "profile.cuenta.dangerZone": "Zona peligrosa",
    "profile.cuenta.dangerIntro": "Acciones que cambian el acceso a tu cuenta.",
    "profile.cuenta.panel.username": "Usuario",
    "profile.cuenta.panel.password": "Contraseña",
    "profile.cuenta.panel.words": "Palabras claves",
    "profile.cuenta.panel.reauth": "Reingreso",

    "profile.words.verifiedHint":
      "Palabras claves ya verificadas para esta sesión.",
    "profile.words.inputLabel": "Palabras claves para {title}",
    "profile.words.inputPlaceholder": "Palabras claves",
    "profile.words.requiredError": "Completa el campo {field}.",
    "profile.words.actionError": "No se pudo completar la acción",
    "profile.words.done": "Listo. Cambio guardado.",
    "profile.words.busy": "Cambiando…",
    "profile.words.changeUsername.title": "Cambiar usuario",
    "profile.words.changeUsername.desc":
      "Demuestra que la cuenta es tuya con tus palabras claves y elige un nuevo usuario.",
    "profile.words.changeUsername.extraLabel": "Nuevo usuario",
    "profile.words.changeUsername.extraPlaceholder": "nuevo-usuario",
    "profile.words.changeUsername.submit": "Cambiar usuario",
    "profile.words.changePassword.title": "Cambiar contraseña",
    "profile.words.changePassword.desc":
      "Demuestra que la cuenta es tuya con tus palabras claves y define una nueva contraseña.",
    "profile.words.changePassword.extraLabel": "Nueva contraseña",
    "profile.words.changePassword.extraPlaceholder": "Nueva contraseña",
    "profile.words.changePassword.submit": "Cambiar contraseña",
    "profile.words.rotate.title": "Rotar palabras claves",
    "profile.words.rotate.desc":
      "Demuestra que la cuenta es tuya con tus palabras claves actuales y genera unas nuevas. Las anteriores quedan anuladas: guarda las nuevas fuera del navegador.",
    "profile.words.rotate.submit": "Rotar palabras claves",
    "profile.words.rotating": "Rotando…",
    "profile.words.rotate.result":
      "Nuevas palabras claves — guárdalas fuera del navegador; solo se muestran una vez:",
    "profile.words.removePassword.title": "Retirar contraseña",
    "profile.words.removePassword.desc":
      "Tu cuenta pasa a ser sin contraseña: alcanza con el botón Entrar. Lo confirmas con tus palabras claves.",
    "profile.words.removePassword.submit": "Retirar contraseña",
    "profile.words.removing": "Retirando…",
    "profile.words.removePassword.confirm": "¿Confirmas el retiro?",
    "profile.words.disableVault.title": "Desactivar bóveda",
    "profile.words.disableVault.desc":
      "Apagar la bóveda quita la autenticación de la instalación. Lo confirmas con tus palabras claves.",
    "profile.words.disableVault.submit": "Desactivar bóveda",
    "profile.words.disabling": "Desactivando…",
    "profile.words.disableVault.confirm": "¿Confirmas la desactivación?",

    "profile.vault.activatedTitle": "Bóveda activada",
    "profile.vault.activatedIntro":
      "Se creó tu cuenta. Estas son tus palabras claves — guárdalas fuera del navegador: solo se muestran una vez.",
    "profile.vault.confirmWords": "Guardé mis palabras",
    "profile.vault.title": "Seguridad / Bóveda",
    "profile.vault.off": "Apagada",
    "profile.vault.intro":
      "La bóveda protege tu instalación con una cuenta y tus palabras claves. Activarla exige demostrar que la cuenta es tuya.",
    "profile.vault.envForced": "La autenticación está forzada por la variable de entorno",
    "profile.vault.activateTitle": "Activar la bóveda",
    "profile.vault.activateIntro":
      "Ya existe una cuenta ({username}). Demuestra que es tuya con tus palabras claves para activar la bóveda.",
    "profile.vault.verifyWordsLabel": "Palabras claves para activar la bóveda",
    "profile.vault.activating": "Activando…",
    "profile.vault.activate": "Activar bóveda",
    "profile.vault.createTitle": "Crear cuenta y activar",
    "profile.vault.createIntro":
      "No hay una cuenta todavía. Créala ahora: la contraseña es opcional y se generan tus palabras claves (se muestran una sola vez).",
    "profile.vault.username": "Usuario",
    "profile.vault.usernamePlaceholder": "tu-usuario",
    "profile.vault.password": "Contraseña (opcional)",
    "profile.vault.passwordPlaceholder":
      "Déjalo vacío para entrar sin contraseña",
    "profile.vault.create": "Crear cuenta y activar",
    "profile.vault.activationError": "No se pudo activar la bóveda",

    "profile.reauth.title": "Intervalo de reingreso",
    "profile.reauth.intro": "Cada cuántos días se te pide reingresar la contraseña.",
    "profile.reauth.daysLabel": "Días entre reingresos",
    "profile.reauth.daysUnit": "días",
    "profile.reauth.invalid": "Ingresa un intervalo válido en días.",
    "profile.reauth.error": "No se pudo ajustar el intervalo",
    "profile.reauth.done": "Listo. Intervalo guardado.",
    "profile.reauth.recommendedToday": "Reingreso recomendado: hoy.",
    "profile.reauth.recommendedInDaysOne": "Reingreso recomendado en 1 día.",
    "profile.reauth.recommendedInDaysMany":
      "Reingreso recomendado en {days} días.",
    "profile.reauth.warning":
      "Si no reingresas tu contraseña, la sesión de Demiurgos se cerrará. Y si olvidaste tu contraseña, solo vas a poder recuperarla con tus palabras claves.",

    "profile.conexiones.assistantTitle": "Asistente de Demiurgos",
    "profile.conexiones.assistantSubtitle":
      "El modelo compartido de Demiurgos: sirve a la Wiki, al bot de Telegram, a la Skill Madre y a los talleres. Las claves solo se envían al backend autenticado.",
    "profile.conexiones.captureTitle": "Captura de ideas",
    "profile.conexiones.captureSubtitle":
      "Hermes / Telegram — ingreso de ideas nativo desde el bot.",

    "profile.mundos.title": "Mundos",
    "profile.mundos.intro":
      "Gestiona los mundos del taller: elimina uno (queda recuperable 30 días en la papelera) o restaura mundos eliminados.",
    "profile.mundos.dangerTitle": "Zona peligrosa",
    "profile.mundos.dangerIntro":
      "Eliminar un mundo lo mueve a la papelera durante 30 días; no se destruye de inmediato.",
    "profile.mundos.empty": "No hay mundos creados todavía.",
    "profile.mundos.deleteActiveReason": "No se puede eliminar el mundo activo",
    "profile.mundos.deleteOnlyReason": "Debe existir al menos un mundo",
    "profile.mundos.loreBadge": "Lore {count}",
    "profile.mundos.charactersBadge": "Personajes {count}",
    "profile.mundos.rename": "Renombrar",
    "profile.mundos.delete": "Borrar",
    "profile.mundos.trashAria": "Papelera de mundos",
    "profile.mundos.migrationAria": "Migración de carpetas",
    "profile.mundos.renameDialogTitle": "Renombrar mundo",
    "profile.mundos.renameDialogMessage":
      "El mundo «{name}» se moverá a un nuevo nombre. Los enlaces viejos siguen funcionando (se redirigen).",
    "profile.mundos.renameDialogConfirm": "Renombrar",

    "error.unknown": "Ocurrió un error inesperado.",
    "error.sessionExpired": "La sesión expiró. Inicia sesión e intenta de nuevo.",
  },
  en: {
    "document.title": "Demiurgos — Wiki",

    "assistant.session.defaultTitle": "New session",

    "common.save": "Save",
    "common.saving": "Saving…",
    "common.cancel": "Cancel",
    "common.continue": "Continue",
    "common.creating": "Creating…",

    "nav.links.tallerHerramientas": "Tools Workshop",
    "nav.links.tallerIdeas": "Ideas Workshop",
    "nav.links.tallerMundo": "World Workshop",
    "nav.soon": "Coming soon",
    "nav.theme.dark": "Theme: dark",
    "nav.theme.light": "Theme: light",
    "nav.toggleTheme": "Change theme",
    "nav.homeAria": "Demiurgos — go home",
    "nav.mainAria": "Main navigation",
    "nav.mobileAria": "Mobile navigation",
    "nav.profileAria": "Profile",
    "nav.profile.openFull": "Full profile",
    "nav.session.title": "Editing session",
    "nav.session.mode.credentials": "Credentials",
    "nav.session.mode.local": "Local",
    "nav.session.checking": "Checking session...",
    "nav.session.active": "Active session",
    "nav.session.closing": "Closing...",
    "nav.session.logout": "Sign out",
    "nav.session.none": "No active account session.",
    "nav.session.local.checking": "Checking local session...",
    "nav.session.local.active": "Local session active",
    "nav.session.local.logout": "Sign out local session",
    "nav.session.local.notStarted": "Local session not started.",
    "nav.session.local.start": "Start local session",
    "nav.session.local.starting": "Starting...",
    "nav.session.local.disabled":
      "Local authentication is disabled. Enable DEMIURGOS_AUTH_MODE=local-dev to try editing.",
    "nav.session.error.fetch": "Could not check the session",
    "nav.session.error.update": "Could not update the local session",
    "nav.system.error.operation": "Could not complete the operation",
    "nav.system.serverDown": "The server did not respond. Restart it or reload the page.",
    "nav.system.restart": "Restart Demiurgos",
    "nav.system.shutdown": "Shut down Demiurgos",
    "nav.system.restarting": "Restarting Demiurgos…",
    "nav.system.shuttingDown": "Shutting down Demiurgos…",
    "nav.system.off": "Demiurgos is off",
    "nav.system.confirm.title.restart": "Restart Demiurgos",
    "nav.system.confirm.title.shutdown": "Shut down Demiurgos",
    "nav.system.confirm.title.logout": "Sign out",
    "nav.system.confirm.message.restart":
      "The connection will drop and the page will go blank for a few seconds. When the server returns, the page will reload automatically; your session is preserved.",
    "nav.system.confirm.message.shutdown":
      "The server will stop and the bot will stop receiving ideas. To use it again, restart it; your session is preserved.",
    "nav.system.confirm.message.logout":
      "Signing out keeps the server and bot running; you can sign back in whenever you want.",
    "nav.system.confirm.confirm.restart": "Restart",
    "nav.system.confirm.confirm.shutdown": "Shut down",
    "nav.system.confirm.confirm.logout": "Sign out",
    "nav.system.transition.restarting":
      "The server is restarting. The page will reload automatically when it returns; your session is preserved.",
    "nav.system.transition.shuttingDown":
      "The server is shutting down. When it finishes, the screen will confirm it; your session is preserved.",
    "nav.system.transition.off":
      "The application stopped completely. Restart it to use it again; your session is preserved.",
    "nav.world.confirm.title": "Change active world",
    "nav.world.confirm.message": "Do you want to change the active world to \"{name}\"?",
    "nav.world.confirm.confirm": "Change",

    "onboarding.title": "Welcome to Demiurgos",
    "onboarding.intro":
      "Initial setup to make the installation operational. You can resume each capability later from the Profile.",
    "onboarding.loadError": "Could not check the installation status.",
    "onboarding.step1.title": "Step 1: language, region, and time zone",
    "onboarding.world.title": "Create your world",
    "onboarding.world.intro":
      "A canonical lowercase tree is created (lore, characters). The world is the last operational step to enter the World Workshop.",
    "onboarding.world.name": "World name",
    "onboarding.world.namePlaceholder": "my-world",
    "onboarding.world.loreSkeleton":
      "Include the recommended Lore structure (empty folders)",
    "onboarding.world.create": "Create world",
    "onboarding.pending.title": "What remains pending",
    "onboarding.pending.aria": "Pending capabilities",
    "onboarding.pending.badge": "Pending",
    "onboarding.pending.none": "No pending capabilities.",
    "onboarding.remote.ai.title": "Demiurgos Assistant (text and vision)",
    "onboarding.remote.ai.desc":
      "Requires a validated local or remote model. Resumed from the Profile.",
    "onboarding.remote.telegram.title": "Telegram",
    "onboarding.remote.telegram.desc":
      "Requires a connection and a configured account. Resumed from the Profile.",
    "onboarding.remote.backup.title": "Backup and restore",
    "onboarding.remote.backup.desc":
      "Requires a connection and consent. Resumed from the Profile.",
    "onboarding.account.title": "Create your account",
    "onboarding.account.intro":
      "The account protects your installation. The password is optional: without it, the Enter button is enough to sign in.",
    "onboarding.account.username": "Username",
    "onboarding.account.usernamePlaceholder": "your-username",
    "onboarding.account.password": "Password (optional)",
    "onboarding.account.passwordPlaceholder":
      "Leave it empty to sign in without a password",
    "onboarding.account.wordsIntro":
      "Creating the account generates your recovery words: they are your only way to recover it if you forget the password. They are shown only once and can never be seen again.",
    "onboarding.account.createError": "Could not create the account",
    "onboarding.account.create": "Create account",
    "onboarding.words.title": "Your recovery words",
    "onboarding.words.intro":
      "Store them in a safe place, outside the browser. They are shown only once: if you lose them and forget the password, the account stays locked forever.",
    "onboarding.words.confirm": "I saved my words",

    "locale.form.intro":
      "Each language is configured independently; the region only suggests values and is never applied silently.",
    "locale.ui": "Interface language",
    "locale.conversation": "Conversation language (assistant)",
    "locale.content": "Content language (world prose)",
    "locale.inherit": "Same as interface",
    "locale.region": "Region (optional; suggests values, never imposes a dialect)",
    "locale.regionPlaceholder": "AR, MX, US…",
    "locale.regionExplicit": "I explicitly confirm the region (override)",
    "locale.timezone": "Time zone (timestamps are stored in UTC)",

    "profile.locale.checking": "Checking configuration…",
    "profile.locale.loadError": "Could not load the configuration states.",
    "profile.locale.title": "Language, region, and time zone",
    "profile.locale.stateLabel": "Status: {label}",

    "profile.title": "Profile",
    "profile.section.cuenta": "Account",
    "profile.section.respaldo": "Backup",
    "profile.section.preferencias": "Preferences",
    "profile.section.conexiones": "Connections",
    "profile.section.mundos": "Worlds",

    "profile.cuenta.checkingVault": "Checking the vault…",
    "profile.cuenta.loadError": "Could not load the vault status.",
    "profile.cuenta.session": "Session",
    "profile.cuenta.sessionActive": "Active",
    "profile.cuenta.sessionOff": "Off",
    "profile.cuenta.account": "Account",
    "profile.cuenta.passwordSet": "password set",
    "profile.cuenta.noPassword": "no password",
    "profile.cuenta.forcedBy": "Forced by",
    "profile.cuenta.recoveryWords": "Recovery words",
    "profile.cuenta.wordsUnlocked": "Unlocked this session",
    "profile.cuenta.wordsLocked": "Locked",
    "profile.cuenta.reauth": "Re-entry",
    "profile.cuenta.today": "today",
    "profile.cuenta.inDaysOne": "in 1 day",
    "profile.cuenta.inDaysMany": "in {days} days",
    "profile.cuenta.noActiveSession":
      "There is no active account session. Sign in to edit and configure the profile.",
    "profile.cuenta.localChecking": "Checking local session…",
    "profile.cuenta.localSession": "Local session",
    "profile.cuenta.localNotStarted":
      "Local session not started. Start it from your profile menu to edit and configure the profile.",
    "profile.cuenta.localDisabled":
      "Local authentication is disabled. Enable DEMIURGOS_AUTH_MODE=local-dev in .env to try editing.",
    "profile.cuenta.manageCredentials": "Manage credentials",
    "profile.cuenta.credentialsAria": "Credential management",
    "profile.cuenta.credentialsIntro":
      "Your recovery words are the ownership key to the account: the first action that asks for them unlocks them for this session and they are remembered until you sign out, without being stored in the browser.",
    "profile.cuenta.dangerZone": "Danger zone",
    "profile.cuenta.dangerIntro": "Actions that change access to your account.",
    "profile.cuenta.panel.username": "Username",
    "profile.cuenta.panel.password": "Password",
    "profile.cuenta.panel.words": "Recovery words",
    "profile.cuenta.panel.reauth": "Re-entry",

    "profile.words.verifiedHint": "Recovery words already verified for this session.",
    "profile.words.inputLabel": "Recovery words for {title}",
    "profile.words.inputPlaceholder": "Recovery words",
    "profile.words.requiredError": "Complete the {field} field.",
    "profile.words.actionError": "Could not complete the action",
    "profile.words.done": "Done. Change saved.",
    "profile.words.busy": "Changing…",
    "profile.words.changeUsername.title": "Change username",
    "profile.words.changeUsername.desc":
      "Prove the account is yours with your recovery words and choose a new username.",
    "profile.words.changeUsername.extraLabel": "New username",
    "profile.words.changeUsername.extraPlaceholder": "new-username",
    "profile.words.changeUsername.submit": "Change username",
    "profile.words.changePassword.title": "Change password",
    "profile.words.changePassword.desc":
      "Prove the account is yours with your recovery words and set a new password.",
    "profile.words.changePassword.extraLabel": "New password",
    "profile.words.changePassword.extraPlaceholder": "New password",
    "profile.words.changePassword.submit": "Change password",
    "profile.words.rotate.title": "Rotate recovery words",
    "profile.words.rotate.desc":
      "Prove the account is yours with your current recovery words and generate new ones. The previous ones are invalidated: keep the new ones outside the browser.",
    "profile.words.rotate.submit": "Rotate recovery words",
    "profile.words.rotating": "Rotating…",
    "profile.words.rotate.result":
      "New recovery words — keep them outside the browser; they are shown only once:",
    "profile.words.removePassword.title": "Remove password",
    "profile.words.removePassword.desc":
      "Your account becomes passwordless: the Enter button is enough. You confirm it with your recovery words.",
    "profile.words.removePassword.submit": "Remove password",
    "profile.words.removing": "Removing…",
    "profile.words.removePassword.confirm": "Do you confirm the removal?",
    "profile.words.disableVault.title": "Disable vault",
    "profile.words.disableVault.desc":
      "Turning off the vault removes authentication from the installation. You confirm it with your recovery words.",
    "profile.words.disableVault.submit": "Disable vault",
    "profile.words.disabling": "Disabling…",
    "profile.words.disableVault.confirm": "Do you confirm the deactivation?",

    "profile.vault.activatedTitle": "Vault activated",
    "profile.vault.activatedIntro":
      "Your account was created. These are your recovery words — keep them outside the browser: they are shown only once.",
    "profile.vault.confirmWords": "I saved my words",
    "profile.vault.title": "Security / Vault",
    "profile.vault.off": "Off",
    "profile.vault.intro":
      "The vault protects your installation with an account and your recovery words. Activating it requires proving the account is yours.",
    "profile.vault.envForced": "Authentication is forced by the environment variable",
    "profile.vault.activateTitle": "Activate the vault",
    "profile.vault.activateIntro":
      "An account already exists ({username}). Prove it is yours with your recovery words to activate the vault.",
    "profile.vault.verifyWordsLabel": "Recovery words to activate the vault",
    "profile.vault.activating": "Activating…",
    "profile.vault.activate": "Activate vault",
    "profile.vault.createTitle": "Create account and activate",
    "profile.vault.createIntro":
      "There is no account yet. Create it now: the password is optional and your recovery words are generated (shown only once).",
    "profile.vault.username": "Username",
    "profile.vault.usernamePlaceholder": "your-username",
    "profile.vault.password": "Password (optional)",
    "profile.vault.passwordPlaceholder": "Leave it empty to sign in without a password",
    "profile.vault.create": "Create account and activate",
    "profile.vault.activationError": "Could not activate the vault",

    "profile.reauth.title": "Re-entry interval",
    "profile.reauth.intro": "How often you are asked to re-enter the password.",
    "profile.reauth.daysLabel": "Days between re-entries",
    "profile.reauth.daysUnit": "days",
    "profile.reauth.invalid": "Enter a valid interval in days.",
    "profile.reauth.error": "Could not adjust the interval",
    "profile.reauth.done": "Done. Interval saved.",
    "profile.reauth.recommendedToday": "Re-entry recommended: today.",
    "profile.reauth.recommendedInDaysOne": "Re-entry recommended in 1 day.",
    "profile.reauth.recommendedInDaysMany": "Re-entry recommended in {days} days.",
    "profile.reauth.warning":
      "If you do not re-enter your password, your Demiurgos session will close. And if you forgot your password, you can only recover it with your recovery words.",

    "profile.conexiones.assistantTitle": "Demiurgos Assistant",
    "profile.conexiones.assistantSubtitle":
      "Demiurgos' shared model: it serves the Wiki, the Telegram bot, the Mother Skill, and the workshops. Keys are only sent to the authenticated backend.",
    "profile.conexiones.captureTitle": "Idea capture",
    "profile.conexiones.captureSubtitle":
      "Hermes / Telegram — native idea intake from the bot.",

    "profile.mundos.title": "Worlds",
    "profile.mundos.intro":
      "Manage the workshop worlds: delete one (it stays recoverable for 30 days in the recycle bin) or restore deleted worlds.",
    "profile.mundos.dangerTitle": "Danger zone",
    "profile.mundos.dangerIntro":
      "Deleting a world moves it to the recycle bin for 30 days; it is not destroyed immediately.",
    "profile.mundos.empty": "No worlds created yet.",
    "profile.mundos.deleteActiveReason": "The active world cannot be deleted",
    "profile.mundos.deleteOnlyReason": "At least one world must exist",
    "profile.mundos.loreBadge": "Lore {count}",
    "profile.mundos.charactersBadge": "Characters {count}",
    "profile.mundos.rename": "Rename",
    "profile.mundos.delete": "Delete",
    "profile.mundos.trashAria": "World recycle bin",
    "profile.mundos.migrationAria": "Folder migration",
    "profile.mundos.renameDialogTitle": "Rename world",
    "profile.mundos.renameDialogMessage":
      "The world \"{name}\" will move to a new name. Old links keep working (they are redirected).",
    "profile.mundos.renameDialogConfirm": "Rename",

    "error.unknown": "An unexpected error occurred.",
    "error.sessionExpired": "The session expired. Sign in and try again.",
  },
} as const;

export type MessageKey = keyof typeof messages.es;

/** Runtime catalogue keyed by language; TS enforces es/en key parity. */
export const CATALOGUE: Record<AppLanguage, Record<MessageKey, string>> = messages;

/** Plain `{name}` interpolation; unknown params are left untouched. */
export function translate(
  language: AppLanguage,
  key: MessageKey,
  params?: TParams,
): string {
  const template = CATALOGUE[language][key];
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match,
  );
}