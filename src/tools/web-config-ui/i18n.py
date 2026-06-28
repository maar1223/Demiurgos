"""
i18n module for web-config-ui onboarding wizard.

Provides translations for all 11 Demiurgos-supported languages, plus
Jinja2 template integration helpers.  Used by wizard routes and screen
templates to render UI in the user's selected language.

Tone constraints:
  - es (neutro): formal usted, verbos sin voseo ("Seleccione", "Configure")
  - es-ar (rioplatense): voseo natural ("Seleccioná", "Configurá")
  - All languages: warm but professional, never generic/cheerful
  - Never expose internal jargon to the user
"""

from __future__ import annotations

from typing import Callable

# ---------------------------------------------------------------------------
# Language metadata
# ---------------------------------------------------------------------------

_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "zh": "中文",
    "hi": "हिन्दी",
    "es": "Español (neutro)",
    "es-ar": "Español (rioplatense)",
    "fr": "Français",
    "ar": "العربية",
    "bn": "বাংলা",
    "pt": "Português",
    "ru": "Русский",
    "ur": "اردو",
}

# Default fallback when a requested language or key is missing
_FALLBACK_LANG = "en"

# ---------------------------------------------------------------------------
# Translation tables — 11 languages × ~49 keys
# ---------------------------------------------------------------------------

_LANGUAGES: dict[str, dict[str, str]] = {
    # ==================================================================
    # English
    # ==================================================================
    "en": {
        # -- Screen 0: Language ----------------------------------------
        "welcome_title": "Welcome to Demiurgos",
        "welcome_subtitle": "Your narrative engine for Hermes. Let's set things up.",
        "select_language": "Choose your language",
        "continue_button": "Continue",

        # -- Screen 1: World -------------------------------------------
        "world_title": "Your World",
        "world_subtitle": "Every saga needs a home. Create a new world or load an existing one.",
        "create_new_world": "Create New World",
        "load_existing_world": "Load Existing World",
        "world_name_label": "World name",
        "world_name_placeholder": "e.g., Thalassia, The Forgotten Depths...",
        "select_folder": "Select folder",
        "supported_formats": "Supported formats",
        "format_docx": ".docx (Word) — fully supported",
        "format_md": ".md (Obsidian) — coming soon",
        "format_notion": "Notion export — coming soon",
        "format_pdf": "PDF — coming soon",

        # -- Screen 2: AI ----------------------------------------------
        "ai_title": "Configure AI",
        "ai_subtitle": "Connect Demiurgos to your LLM providers. Text model is required; vision is optional.",
        "provider_label": "Provider",
        "endpoint_label": "Endpoint URL",
        "api_key_label": "API Key",
        "model_text_label": "Text Model",
        "model_vision_label": "Vision Model",
        "test_connection": "Test Connection",
        "testing": "Testing connection…",
        "connection_success": "Connection successful — {count} models found",
        "connection_error": "Connection failed",
        "same_as_text": "Same as text model",
        "vision_warning": "{model} does not support vision. Choose a model marked with 👁️ for vision tasks.",
        "save_config": "Save Configuration",
        "select_model": "Select a model…",
        "select_provider": "Select a provider…",
        "discover_models": "Discover models",

        # -- Screen 3: Images ------------------------------------------
        "images_title": "Image Generation",
        "images_subtitle": "Optional — configure an image generation provider for visual storytelling.",
        "skip_for_now": "Skip for now",
        "configure_later": "Configure later",

        # -- Screen 4: Chats -------------------------------------------
        "chats_title": "Chat Platforms",
        "chats_subtitle": "Optional — connect Demiurgos to Telegram or Discord for mobile access.",

        # -- Screen 5: Backup ------------------------------------------
        "backup_title": "Backup & Sync",
        "backup_subtitle": "Optional — set up automated backups of your worlds and lore.",

        # -- Screen 6: Summary -----------------------------------------
        "summary_title": "Ready to Begin",
        "summary_subtitle": "Here is a summary of your configuration. You can change anything later.",
        "start_using": "Start Using Demiurgos",
        "go_back": "Go Back",
        "world_created": "World created",
        "ai_configured": "AI configured",
        "configured": "Configured",
        "skipped": "Skipped",
        "edit": "Edit",

        # -- Navigation ------------------------------------------------
        "next": "Next",
        "back": "Back",
        "step_x_of_y": "Step {current} of {total}",

        # -- Errors ----------------------------------------------------
        "error_generic": "Something went wrong. Please try again.",
        "error_required_field": "This field is required.",
        "error_connection": "Could not connect to the server. Check your network and try again.",

        # -- Model tags ------------------------------------------------
        "vision_tag_confirmed": "👁️ vision",
        "vision_tag_text_only": "✍️ text",
        "vision_tag_unknown": "❓ unknown",
    },

    # ==================================================================
    # Chinese (Simplified)
    # ==================================================================
    "zh": {
        "welcome_title": "欢迎使用 Demiurgos",
        "welcome_subtitle": "您的 Hermes 叙事引擎。让我们开始配置。",
        "select_language": "选择您的语言",
        "continue_button": "继续",

        "world_title": "您的世界",
        "world_subtitle": "每个传奇都需要一个家园。创建新世界或加载已有世界。",
        "create_new_world": "创建新世界",
        "load_existing_world": "加载已有世界",
        "world_name_label": "世界名称",
        "world_name_placeholder": "例如：深海之境、遗忘深渊…",
        "select_folder": "选择文件夹",
        "supported_formats": "支持的格式",
        "format_docx": ".docx (Word) — 完全支持",
        "format_md": ".md (Obsidian) — 即将推出",
        "format_notion": "Notion 导出 — 即将推出",
        "format_pdf": "PDF — 即将推出",

        "ai_title": "配置 AI",
        "ai_subtitle": "将 Demiurgos 连接到您的 LLM 提供商。文本模型为必选，视觉模型为可选。",
        "provider_label": "提供商",
        "endpoint_label": "端点 URL",
        "api_key_label": "API 密钥",
        "model_text_label": "文本模型",
        "model_vision_label": "视觉模型",
        "test_connection": "测试连接",
        "testing": "正在测试连接…",
        "connection_success": "连接成功 — 找到 {count} 个模型",
        "connection_error": "连接失败",
        "same_as_text": "与文本模型相同",
        "vision_warning": "{model} 不支持视觉。请选择标有 👁️ 的模型用于视觉任务。",
        "save_config": "保存配置",
        "select_model": "选择模型…",
        "select_provider": "选择提供商…",
        "discover_models": "发现模型",

        "images_title": "图像生成",
        "images_subtitle": "可选 — 配置图像生成提供商用于视觉叙事。",
        "skip_for_now": "暂时跳过",
        "configure_later": "稍后配置",

        "chats_title": "聊天平台",
        "chats_subtitle": "可选 — 将 Demiurgos 连接到 Telegram 或 Discord 以实现移动访问。",

        "backup_title": "备份与同步",
        "backup_subtitle": "可选 — 为您的世界和背景设定设置自动备份。",

        "summary_title": "准备开始",
        "summary_subtitle": "以下是您的配置摘要。您可以随时更改。",
        "start_using": "开始使用 Demiurgos",
        "go_back": "返回",
        "world_created": "世界已创建",
        "ai_configured": "AI 已配置",
        "configured": "已配置",
        "skipped": "已跳过",
        "edit": "编辑",

        "next": "下一步",
        "back": "上一步",
        "step_x_of_y": "第 {current} 步，共 {total} 步",

        "error_generic": "出了点问题。请重试。",
        "error_required_field": "此字段为必填项。",
        "error_connection": "无法连接到服务器。请检查网络后重试。",

        "vision_tag_confirmed": "👁️ 视觉",
        "vision_tag_text_only": "✍️ 文本",
        "vision_tag_unknown": "❓ 未知",
    },

    # ==================================================================
    # Hindi
    # ==================================================================
    "hi": {
        "welcome_title": "Demiurgos में आपका स्वागत है",
        "welcome_subtitle": "Hermes के लिए आपका कथा इंजन। आइए सेटअप करें।",
        "select_language": "अपनी भाषा चुनें",
        "continue_button": "जारी रखें",

        "world_title": "आपकी दुनिया",
        "world_subtitle": "हर गाथा को एक घर चाहिए। नई दुनिया बनाएँ या मौजूदा लोड करें।",
        "create_new_world": "नई दुनिया बनाएँ",
        "load_existing_world": "मौजूदा दुनिया लोड करें",
        "world_name_label": "दुनिया का नाम",
        "world_name_placeholder": "जैसे, थैलेसिया, भूली हुई गहराइयाँ…",
        "select_folder": "फ़ोल्डर चुनें",
        "supported_formats": "समर्थित प्रारूप",
        "format_docx": ".docx (Word) — पूरी तरह समर्थित",
        "format_md": ".md (Obsidian) — जल्द आ रहा है",
        "format_notion": "Notion निर्यात — जल्द आ रहा है",
        "format_pdf": "PDF — जल्द आ रहा है",

        "ai_title": "AI कॉन्फ़िगर करें",
        "ai_subtitle": "Demiurgos को अपने LLM प्रदाताओं से जोड़ें। टेक्स्ट मॉडल आवश्यक है; विज़न वैकल्पिक है।",
        "provider_label": "प्रदाता",
        "endpoint_label": "एंडपॉइंट URL",
        "api_key_label": "API कुंजी",
        "model_text_label": "टेक्स्ट मॉडल",
        "model_vision_label": "विज़न मॉडल",
        "test_connection": "कनेक्शन जाँचें",
        "testing": "कनेक्शन जाँच रहे हैं…",
        "connection_success": "कनेक्शन सफल — {count} मॉडल मिले",
        "connection_error": "कनेक्शन विफल",
        "same_as_text": "टेक्स्ट मॉडल के समान",
        "vision_warning": "{model} विज़न का समर्थन नहीं करता। विज़न कार्यों के लिए 👁️ चिह्नित मॉडल चुनें।",
        "save_config": "कॉन्फ़िगरेशन सहेजें",
        "select_model": "मॉडल चुनें…",
        "select_provider": "प्रदाता चुनें…",
        "discover_models": "मॉडल खोजें",

        "images_title": "छवि निर्माण",
        "images_subtitle": "वैकल्पिक — दृश्य कहानी के लिए छवि निर्माण प्रदाता कॉन्फ़िगर करें।",
        "skip_for_now": "अभी छोड़ें",
        "configure_later": "बाद में कॉन्फ़िगर करें",

        "chats_title": "चैट प्लेटफ़ॉर्म",
        "chats_subtitle": "वैकल्पिक — मोबाइल एक्सेस के लिए Demiurgos को Telegram या Discord से जोड़ें।",

        "backup_title": "बैकअप और सिंक",
        "backup_subtitle": "वैकल्पिक — अपनी दुनियाओं और लोर का स्वचालित बैकअप सेट करें।",

        "summary_title": "शुरू करने के लिए तैयार",
        "summary_subtitle": "यहाँ आपके कॉन्फ़िगरेशन का सारांश है। आप बाद में कुछ भी बदल सकते हैं।",
        "start_using": "Demiurgos का उपयोग शुरू करें",
        "go_back": "वापस जाएँ",
        "world_created": "दुनिया बनाई गई",
        "ai_configured": "AI कॉन्फ़िगर किया गया",
        "configured": "कॉन्फ़िगर किया गया",
        "skipped": "छोड़ा गया",
        "edit": "संपादित करें",

        "next": "अगला",
        "back": "पिछला",
        "step_x_of_y": "चरण {current} / {total}",

        "error_generic": "कुछ गलत हो गया। कृपया पुनः प्रयास करें।",
        "error_required_field": "यह फ़ील्ड आवश्यक है।",
        "error_connection": "सर्वर से कनेक्ट नहीं हो सका। अपना नेटवर्क जाँचें और पुनः प्रयास करें।",

        "vision_tag_confirmed": "👁️ विज़न",
        "vision_tag_text_only": "✍️ टेक्स्ट",
        "vision_tag_unknown": "❓ अज्ञात",
    },

    # ==================================================================
    # Spanish (neutral — formal usted, no voseo)
    # ==================================================================
    "es": {
        "welcome_title": "Bienvenido a Demiurgos",
        "welcome_subtitle": "Su motor narrativo para Hermes. Configuremos todo.",
        "select_language": "Seleccione su idioma",
        "continue_button": "Continuar",

        "world_title": "Su Mundo",
        "world_subtitle": "Toda saga necesita un hogar. Cree un nuevo mundo o cargue uno existente.",
        "create_new_world": "Crear Nuevo Mundo",
        "load_existing_world": "Cargar Mundo Existente",
        "world_name_label": "Nombre del mundo",
        "world_name_placeholder": "ej., Thalassia, Las Profundidades Olvidadas…",
        "select_folder": "Seleccionar carpeta",
        "supported_formats": "Formatos soportados",
        "format_docx": ".docx (Word) — totalmente soportado",
        "format_md": ".md (Obsidian) — próximamente",
        "format_notion": "Exportación de Notion — próximamente",
        "format_pdf": "PDF — próximamente",

        "ai_title": "Configurar IA",
        "ai_subtitle": "Conecte Demiurgos a sus proveedores LLM. El modelo de texto es obligatorio; visión es opcional.",
        "provider_label": "Proveedor",
        "endpoint_label": "URL del endpoint",
        "api_key_label": "API Key",
        "model_text_label": "Modelo de texto",
        "model_vision_label": "Modelo de visión",
        "test_connection": "Probar Conexión",
        "testing": "Probando conexión…",
        "connection_success": "Conexión exitosa — {count} modelos encontrados",
        "connection_error": "Error de conexión",
        "same_as_text": "Mismo que modelo de texto",
        "vision_warning": "{model} no soporta visión. Seleccione un modelo marcado con 👁️ para tareas de visión.",
        "save_config": "Guardar Configuración",
        "select_model": "Seleccione un modelo…",
        "select_provider": "Seleccione un proveedor…",
        "discover_models": "Descubrir modelos",

        "images_title": "Generación de Imágenes",
        "images_subtitle": "Opcional — configure un proveedor de imágenes para narración visual.",
        "skip_for_now": "Saltar por ahora",
        "configure_later": "Configurar después",

        "chats_title": "Plataformas de Chat",
        "chats_subtitle": "Opcional — conecte Demiurgos a Telegram o Discord para acceso móvil.",

        "backup_title": "Respaldo y Sincronización",
        "backup_subtitle": "Opcional — configure respaldos automáticos de sus mundos y lore.",

        "summary_title": "Listo para Empezar",
        "summary_subtitle": "Aquí tiene un resumen de su configuración. Puede cambiar todo después.",
        "start_using": "Comenzar a Usar Demiurgos",
        "go_back": "Volver",
        "world_created": "Mundo creado",
        "ai_configured": "IA configurada",
        "configured": "Configurado",
        "skipped": "Omitido",
        "edit": "Editar",

        "next": "Siguiente",
        "back": "Atrás",
        "step_x_of_y": "Paso {current} de {total}",

        "error_generic": "Algo salió mal. Intente de nuevo.",
        "error_required_field": "Este campo es obligatorio.",
        "error_connection": "No se pudo conectar al servidor. Verifique su red e intente de nuevo.",

        "vision_tag_confirmed": "👁️ visión",
        "vision_tag_text_only": "✍️ texto",
        "vision_tag_unknown": "❓ desconocido",
    },

    # ==================================================================
    # Spanish (Rioplatense — voseo natural)
    # ==================================================================
    "es-ar": {
        "welcome_title": "Bienvenido a Demiurgos",
        "welcome_subtitle": "Tu motor narrativo para Hermes. Configuremos todo.",
        "select_language": "Elegí tu idioma",
        "continue_button": "Continuar",

        "world_title": "Tu Mundo",
        "world_subtitle": "Toda saga necesita un hogar. Creá un nuevo mundo o cargá uno existente.",
        "create_new_world": "Crear Nuevo Mundo",
        "load_existing_world": "Cargar Mundo Existente",
        "world_name_label": "Nombre del mundo",
        "world_name_placeholder": "ej., Thalassia, Las Profundidades Olvidadas…",
        "select_folder": "Seleccionar carpeta",
        "supported_formats": "Formatos soportados",
        "format_docx": ".docx (Word) — totalmente soportado",
        "format_md": ".md (Obsidian) — próximamente",
        "format_notion": "Exportación de Notion — próximamente",
        "format_pdf": "PDF — próximamente",

        "ai_title": "Configurar IA",
        "ai_subtitle": "Conectá Demiurgos a tus proveedores LLM. El modelo de texto es obligatorio; visión es opcional.",
        "provider_label": "Proveedor",
        "endpoint_label": "URL del endpoint",
        "api_key_label": "API Key",
        "model_text_label": "Modelo de texto",
        "model_vision_label": "Modelo de visión",
        "test_connection": "Probar Conexión",
        "testing": "Probando conexión…",
        "connection_success": "Conexión exitosa — {count} modelos encontrados",
        "connection_error": "Error de conexión",
        "same_as_text": "Mismo que modelo de texto",
        "vision_warning": "{model} no soporta visión. Elegí un modelo marcado con 👁️ para tareas de visión.",
        "save_config": "Guardar Configuración",
        "select_model": "Seleccioná un modelo…",
        "select_provider": "Seleccioná un proveedor…",
        "discover_models": "Descubrir modelos",

        "images_title": "Generación de Imágenes",
        "images_subtitle": "Opcional — configurá un proveedor de imágenes para narración visual.",
        "skip_for_now": "Saltar por ahora",
        "configure_later": "Configurar después",

        "chats_title": "Plataformas de Chat",
        "chats_subtitle": "Opcional — conectá Demiurgos a Telegram o Discord para acceso móvil.",

        "backup_title": "Respaldo y Sincronización",
        "backup_subtitle": "Opcional — configurá respaldos automáticos de tus mundos y lore.",

        "summary_title": "Listo para Arrancar",
        "summary_subtitle": "Acá tenés un resumen de tu configuración. Podés cambiar todo después.",
        "start_using": "Comenzar a Usar Demiurgos",
        "go_back": "Volver",
        "world_created": "Mundo creado",
        "ai_configured": "IA configurada",
        "configured": "Configurado",
        "skipped": "Omitido",
        "edit": "Editar",

        "next": "Siguiente",
        "back": "Atrás",
        "step_x_of_y": "Paso {current} de {total}",

        "error_generic": "Algo salió mal. Intentá de nuevo.",
        "error_required_field": "Este campo es obligatorio.",
        "error_connection": "No se pudo conectar al servidor. Verificá tu red e intentá de nuevo.",

        "vision_tag_confirmed": "👁️ visión",
        "vision_tag_text_only": "✍️ texto",
        "vision_tag_unknown": "❓ desconocido",
    },

    # ==================================================================
    # French
    # ==================================================================
    "fr": {
        "welcome_title": "Bienvenue sur Demiurgos",
        "welcome_subtitle": "Votre moteur narratif pour Hermes. Configurons tout cela.",
        "select_language": "Choisissez votre langue",
        "continue_button": "Continuer",

        "world_title": "Votre Monde",
        "world_subtitle": "Toute saga a besoin d'un foyer. Créez un nouveau monde ou chargez-en un existant.",
        "create_new_world": "Créer un Nouveau Monde",
        "load_existing_world": "Charger un Monde Existant",
        "world_name_label": "Nom du monde",
        "world_name_placeholder": "ex., Thalassia, Les Profondeurs Oubliées…",
        "select_folder": "Sélectionner un dossier",
        "supported_formats": "Formats supportés",
        "format_docx": ".docx (Word) — entièrement supporté",
        "format_md": ".md (Obsidian) — bientôt disponible",
        "format_notion": "Export Notion — bientôt disponible",
        "format_pdf": "PDF — bientôt disponible",

        "ai_title": "Configurer l'IA",
        "ai_subtitle": "Connectez Demiurgos à vos fournisseurs LLM. Le modèle texte est requis ; la vision est optionnelle.",
        "provider_label": "Fournisseur",
        "endpoint_label": "URL du endpoint",
        "api_key_label": "Clé API",
        "model_text_label": "Modèle texte",
        "model_vision_label": "Modèle vision",
        "test_connection": "Tester la Connexion",
        "testing": "Test de connexion…",
        "connection_success": "Connexion réussie — {count} modèles trouvés",
        "connection_error": "Échec de connexion",
        "same_as_text": "Identique au modèle texte",
        "vision_warning": "{model} ne supporte pas la vision. Choisissez un modèle marqué 👁️ pour les tâches visuelles.",
        "save_config": "Enregistrer la Configuration",
        "select_model": "Sélectionnez un modèle…",
        "select_provider": "Sélectionnez un fournisseur…",
        "discover_models": "Découvrir les modèles",

        "images_title": "Génération d'Images",
        "images_subtitle": "Optionnel — configurez un fournisseur d'images pour la narration visuelle.",
        "skip_for_now": "Passer pour l'instant",
        "configure_later": "Configurer plus tard",

        "chats_title": "Plateformes de Chat",
        "chats_subtitle": "Optionnel — connectez Demiurgos à Telegram ou Discord pour un accès mobile.",

        "backup_title": "Sauvegarde et Synchro",
        "backup_subtitle": "Optionnel — configurez des sauvegardes automatiques de vos mondes et lore.",

        "summary_title": "Prêt à Démarrer",
        "summary_subtitle": "Voici un résumé de votre configuration. Vous pouvez tout modifier plus tard.",
        "start_using": "Commencer à Utiliser Demiurgos",
        "go_back": "Retour",
        "world_created": "Monde créé",
        "ai_configured": "IA configurée",
        "configured": "Configuré",
        "skipped": "Ignoré",
        "edit": "Modifier",

        "next": "Suivant",
        "back": "Retour",
        "step_x_of_y": "Étape {current} sur {total}",

        "error_generic": "Quelque chose s'est mal passé. Veuillez réessayer.",
        "error_required_field": "Ce champ est obligatoire.",
        "error_connection": "Impossible de se connecter au serveur. Vérifiez votre réseau et réessayez.",

        "vision_tag_confirmed": "👁️ vision",
        "vision_tag_text_only": "✍️ texte",
        "vision_tag_unknown": "❓ inconnu",
    },

    # ==================================================================
    # Arabic
    # ==================================================================
    "ar": {
        "welcome_title": "مرحباً بك في Demiurgos",
        "welcome_subtitle": "محركك السردي لـ Hermes. هيا لنُعد الإعدادات.",
        "select_language": "اختر لغتك",
        "continue_button": "متابعة",

        "world_title": "عالمك",
        "world_subtitle": "كل ملحمة تحتاج إلى موطن. أنشئ عالماً جديداً أو حمّل عالماً موجوداً.",
        "create_new_world": "إنشاء عالم جديد",
        "load_existing_world": "تحميل عالم موجود",
        "world_name_label": "اسم العالم",
        "world_name_placeholder": "مثال: ثالاسيا، الأعماق المنسية…",
        "select_folder": "اختيار مجلد",
        "supported_formats": "الصيغ المدعومة",
        "format_docx": ".docx (Word) — مدعوم بالكامل",
        "format_md": ".md (Obsidian) — قريباً",
        "format_notion": "تصدير Notion — قريباً",
        "format_pdf": "PDF — قريباً",

        "ai_title": "تكوين الذكاء الاصطناعي",
        "ai_subtitle": "اربط Demiurgos بمزوّدي LLM. نموذج النص مطلوب؛ الرؤية اختيارية.",
        "provider_label": "المزوّد",
        "endpoint_label": "رابط النقطة الطرفية",
        "api_key_label": "مفتاح API",
        "model_text_label": "نموذج النص",
        "model_vision_label": "نموذج الرؤية",
        "test_connection": "اختبار الاتصال",
        "testing": "جارٍ اختبار الاتصال…",
        "connection_success": "تم الاتصال بنجاح — تم العثور على {count} نموذج",
        "connection_error": "فشل الاتصال",
        "same_as_text": "نفس نموذج النص",
        "vision_warning": "{model} لا يدعم الرؤية. اختر نموذجاً موسوماً بـ 👁️ لمهام الرؤية.",
        "save_config": "حفظ التكوين",
        "select_model": "اختر نموذجاً…",
        "select_provider": "اختر مزوّداً…",
        "discover_models": "اكتشاف النماذج",

        "images_title": "توليد الصور",
        "images_subtitle": "اختياري — كوّن مزوّد صور للسرد البصري.",
        "skip_for_now": "تخطَّ الآن",
        "configure_later": "التكوين لاحقاً",

        "chats_title": "منصات الدردشة",
        "chats_subtitle": "اختياري — اربط Demiurgos بـ Telegram أو Discord للوصول عبر الجوال.",

        "backup_title": "النسخ الاحتياطي والمزامنة",
        "backup_subtitle": "اختياري — إعداد نسخ احتياطية تلقائية لعوالمك ومعلوماتك.",

        "summary_title": "جاهز للبدء",
        "summary_subtitle": "إليك ملخص لإعداداتك. يمكنك تغيير أي شيء لاحقاً.",
        "start_using": "ابدأ استخدام Demiurgos",
        "go_back": "رجوع",
        "world_created": "تم إنشاء العالم",
        "ai_configured": "تم تكوين الذكاء الاصطناعي",
        "configured": "مُكوَّن",
        "skipped": "تم التخطي",
        "edit": "تعديل",

        "next": "التالي",
        "back": "السابق",
        "step_x_of_y": "الخطوة {current} من {total}",

        "error_generic": "حدث خطأ ما. يرجى المحاولة مرة أخرى.",
        "error_required_field": "هذا الحقل مطلوب.",
        "error_connection": "تعذر الاتصال بالخادم. تحقق من شبكتك وحاول مرة أخرى.",

        "vision_tag_confirmed": "👁️ رؤية",
        "vision_tag_text_only": "✍️ نص",
        "vision_tag_unknown": "❓ غير معروف",
    },

    # ==================================================================
    # Bengali
    # ==================================================================
    "bn": {
        "welcome_title": "Demiurgos-এ স্বাগতম",
        "welcome_subtitle": "Hermes-এর জন্য আপনার কাহিনী ইঞ্জিন। চলুন সেটআপ করি।",
        "select_language": "আপনার ভাষা নির্বাচন করুন",
        "continue_button": "চালিয়ে যান",

        "world_title": "আপনার বিশ্ব",
        "world_subtitle": "প্রতিটি গাথার একটি ঘর প্রয়োজন। নতুন বিশ্ব তৈরি করুন বা বিদ্যমান লোড করুন।",
        "create_new_world": "নতুন বিশ্ব তৈরি করুন",
        "load_existing_world": "বিদ্যমান বিশ্ব লোড করুন",
        "world_name_label": "বিশ্বের নাম",
        "world_name_placeholder": "যেমন, থ্যালাসিয়া, বিস্মৃত গভীরতা…",
        "select_folder": "ফোল্ডার নির্বাচন করুন",
        "supported_formats": "সমর্থিত ফরম্যাট",
        "format_docx": ".docx (Word) — সম্পূর্ণ সমর্থিত",
        "format_md": ".md (Obsidian) — শীঘ্রই আসছে",
        "format_notion": "Notion রপ্তানি — শীঘ্রই আসছে",
        "format_pdf": "PDF — শীঘ্রই আসছে",

        "ai_title": "AI কনফিগার করুন",
        "ai_subtitle": "Demiurgos-কে আপনার LLM প্রদানকারীদের সাথে সংযুক্ত করুন। টেক্সট মডেল আবশ্যক; ভিশন ঐচ্ছিক।",
        "provider_label": "প্রদানকারী",
        "endpoint_label": "এন্ডপয়েন্ট URL",
        "api_key_label": "API কী",
        "model_text_label": "টেক্সট মডেল",
        "model_vision_label": "ভিশন মডেল",
        "test_connection": "সংযোগ পরীক্ষা করুন",
        "testing": "সংযোগ পরীক্ষা করা হচ্ছে…",
        "connection_success": "সংযোগ সফল — {count}টি মডেল পাওয়া গেছে",
        "connection_error": "সংযোগ ব্যর্থ",
        "same_as_text": "টেক্সট মডেলের মতোই",
        "vision_warning": "{model} ভিশন সমর্থন করে না। ভিশন কাজের জন্য 👁️ চিহ্নিত মডেল নির্বাচন করুন।",
        "save_config": "কনফিগারেশন সংরক্ষণ করুন",
        "select_model": "মডেল নির্বাচন করুন…",
        "select_provider": "প্রদানকারী নির্বাচন করুন…",
        "discover_models": "মডেল আবিষ্কার করুন",

        "images_title": "ছবি তৈরি",
        "images_subtitle": "ঐচ্ছিক — দৃশ্যকাহিনীর জন্য ছবি তৈরির প্রদানকারী কনফিগার করুন।",
        "skip_for_now": "এখন skip করুন",
        "configure_later": "পরে কনফিগার করুন",

        "chats_title": "চ্যাট প্ল্যাটফর্ম",
        "chats_subtitle": "ঐচ্ছিক — মোবাইল অ্যাক্সেসের জন্য Demiurgos-কে Telegram বা Discord-এ সংযুক্ত করুন।",

        "backup_title": "ব্যাকআপ ও সিঙ্ক",
        "backup_subtitle": "ঐচ্ছিক — আপনার বিশ্ব ও লোরের স্বয়ংক্রিয় ব্যাকআপ সেটআপ করুন।",

        "summary_title": "শুরু করার জন্য প্রস্তুত",
        "summary_subtitle": "এখানে আপনার কনফিগারেশনের সারসংক্ষেপ। আপনি পরে যেকোনো কিছু পরিবর্তন করতে পারবেন।",
        "start_using": "Demiurgos ব্যবহার শুরু করুন",
        "go_back": "ফিরে যান",
        "world_created": "বিশ্ব তৈরি হয়েছে",
        "ai_configured": "AI কনফিগার করা হয়েছে",
        "configured": "কনফিগার করা হয়েছে",
        "skipped": "বাদ দেওয়া হয়েছে",
        "edit": "সম্পাদনা",

        "next": "পরবর্তী",
        "back": "পূর্ববর্তী",
        "step_x_of_y": "ধাপ {current} / {total}",

        "error_generic": "কিছু ভুল হয়েছে। অনুগ্রহ করে আবার চেষ্টা করুন।",
        "error_required_field": "এই ক্ষেত্রটি আবশ্যক।",
        "error_connection": "সার্ভারে সংযোগ করা যায়নি। আপনার নেটওয়ার্ক পরীক্ষা করে আবার চেষ্টা করুন।",

        "vision_tag_confirmed": "👁️ ভিশন",
        "vision_tag_text_only": "✍️ টেক্সট",
        "vision_tag_unknown": "❓ অজানা",
    },

    # ==================================================================
    # Portuguese
    # ==================================================================
    "pt": {
        "welcome_title": "Bem-vindo ao Demiurgos",
        "welcome_subtitle": "Seu motor narrativo para o Hermes. Vamos configurar.",
        "select_language": "Escolha seu idioma",
        "continue_button": "Continuar",

        "world_title": "Seu Mundo",
        "world_subtitle": "Toda saga precisa de um lar. Crie um novo mundo ou carregue um existente.",
        "create_new_world": "Criar Novo Mundo",
        "load_existing_world": "Carregar Mundo Existente",
        "world_name_label": "Nome do mundo",
        "world_name_placeholder": "ex., Thalassia, As Profundezas Esquecidas…",
        "select_folder": "Selecionar pasta",
        "supported_formats": "Formatos suportados",
        "format_docx": ".docx (Word) — totalmente suportado",
        "format_md": ".md (Obsidian) — em breve",
        "format_notion": "Exportação do Notion — em breve",
        "format_pdf": "PDF — em breve",

        "ai_title": "Configurar IA",
        "ai_subtitle": "Conecte o Demiurgos aos seus provedores LLM. O modelo de texto é obrigatório; visão é opcional.",
        "provider_label": "Provedor",
        "endpoint_label": "URL do endpoint",
        "api_key_label": "Chave API",
        "model_text_label": "Modelo de texto",
        "model_vision_label": "Modelo de visão",
        "test_connection": "Testar Conexão",
        "testing": "Testando conexão…",
        "connection_success": "Conexão bem-sucedida — {count} modelos encontrados",
        "connection_error": "Falha na conexão",
        "same_as_text": "Mesmo que modelo de texto",
        "vision_warning": "{model} não suporta visão. Escolha um modelo marcado com 👁️ para tarefas de visão.",
        "save_config": "Salvar Configuração",
        "select_model": "Selecione um modelo…",
        "select_provider": "Selecione um provedor…",
        "discover_models": "Descobrir modelos",

        "images_title": "Geração de Imagens",
        "images_subtitle": "Opcional — configure um provedor de imagens para narrativa visual.",
        "skip_for_now": "Pular por enquanto",
        "configure_later": "Configurar depois",

        "chats_title": "Plataformas de Chat",
        "chats_subtitle": "Opcional — conecte o Demiurgos ao Telegram ou Discord para acesso móvel.",

        "backup_title": "Backup e Sincronização",
        "backup_subtitle": "Opcional — configure backups automáticos dos seus mundos e lore.",

        "summary_title": "Pronto para Começar",
        "summary_subtitle": "Aqui está um resumo da sua configuração. Você pode alterar tudo depois.",
        "start_using": "Começar a Usar o Demiurgos",
        "go_back": "Voltar",
        "world_created": "Mundo criado",
        "ai_configured": "IA configurada",
        "configured": "Configurado",
        "skipped": "Pulado",
        "edit": "Editar",

        "next": "Próximo",
        "back": "Anterior",
        "step_x_of_y": "Etapa {current} de {total}",

        "error_generic": "Algo deu errado. Tente novamente.",
        "error_required_field": "Este campo é obrigatório.",
        "error_connection": "Não foi possível conectar ao servidor. Verifique sua rede e tente novamente.",

        "vision_tag_confirmed": "👁️ visão",
        "vision_tag_text_only": "✍️ texto",
        "vision_tag_unknown": "❓ desconhecido",
    },

    # ==================================================================
    # Russian
    # ==================================================================
    "ru": {
        "welcome_title": "Добро пожаловать в Demiurgos",
        "welcome_subtitle": "Ваш нарративный движок для Hermes. Давайте настроим всё.",
        "select_language": "Выберите язык",
        "continue_button": "Продолжить",

        "world_title": "Ваш Мир",
        "world_subtitle": "Каждой саге нужен дом. Создайте новый мир или загрузите существующий.",
        "create_new_world": "Создать Новый Мир",
        "load_existing_world": "Загрузить Существующий Мир",
        "world_name_label": "Название мира",
        "world_name_placeholder": "напр., Талассия, Забытые Глубины…",
        "select_folder": "Выбрать папку",
        "supported_formats": "Поддерживаемые форматы",
        "format_docx": ".docx (Word) — полностью поддерживается",
        "format_md": ".md (Obsidian) — скоро",
        "format_notion": "Экспорт из Notion — скоро",
        "format_pdf": "PDF — скоро",

        "ai_title": "Настройка ИИ",
        "ai_subtitle": "Подключите Demiurgos к вашим LLM-провайдерам. Текстовая модель обязательна; зрение — опционально.",
        "provider_label": "Провайдер",
        "endpoint_label": "URL эндпоинта",
        "api_key_label": "API-ключ",
        "model_text_label": "Текстовая модель",
        "model_vision_label": "Модель зрения",
        "test_connection": "Проверить Соединение",
        "testing": "Проверка соединения…",
        "connection_success": "Соединение успешно — найдено {count} моделей",
        "connection_error": "Ошибка соединения",
        "same_as_text": "Как текстовая модель",
        "vision_warning": "{model} не поддерживает зрение. Выберите модель с 👁️ для задач со зрением.",
        "save_config": "Сохранить Конфигурацию",
        "select_model": "Выберите модель…",
        "select_provider": "Выберите провайдера…",
        "discover_models": "Найти модели",

        "images_title": "Генерация Изображений",
        "images_subtitle": "Опционально — настройте провайдера изображений для визуального повествования.",
        "skip_for_now": "Пропустить",
        "configure_later": "Настроить позже",

        "chats_title": "Чат-Платформы",
        "chats_subtitle": "Опционально — подключите Demiurgos к Telegram или Discord для мобильного доступа.",

        "backup_title": "Резервное Копирование",
        "backup_subtitle": "Опционально — настройте автоматическое резервное копирование миров и лора.",

        "summary_title": "Готовы к Началу",
        "summary_subtitle": "Вот сводка вашей конфигурации. Всё можно изменить позже.",
        "start_using": "Начать Использовать Demiurgos",
        "go_back": "Назад",
        "world_created": "Мир создан",
        "ai_configured": "ИИ настроен",
        "configured": "Настроено",
        "skipped": "Пропущено",
        "edit": "Изменить",

        "next": "Далее",
        "back": "Назад",
        "step_x_of_y": "Шаг {current} из {total}",

        "error_generic": "Что-то пошло не так. Попробуйте снова.",
        "error_required_field": "Это поле обязательно для заполнения.",
        "error_connection": "Не удалось подключиться к серверу. Проверьте сеть и попробуйте снова.",

        "vision_tag_confirmed": "👁️ зрение",
        "vision_tag_text_only": "✍️ текст",
        "vision_tag_unknown": "❓ неизвестно",
    },

    # ==================================================================
    # Urdu
    # ==================================================================
    "ur": {
        "welcome_title": "Demiurgos میں خوش آمدید",
        "welcome_subtitle": "Hermes کے لیے آپ کا کہانی انجن۔ آئیے سیٹ اپ کرتے ہیں۔",
        "select_language": "اپنی زبان منتخب کریں",
        "continue_button": "جاری رکھیں",

        "world_title": "آپ کی دنیا",
        "world_subtitle": "ہر کہانی کو ایک گھر چاہیے۔ نئی دنیا بنائیں یا موجودہ لوڈ کریں۔",
        "create_new_world": "نئی دنیا بنائیں",
        "load_existing_world": "موجودہ دنیا لوڈ کریں",
        "world_name_label": "دنیا کا نام",
        "world_name_placeholder": "مثلاً، تھیلیسیا، بھولی ہوئی گہرائیاں…",
        "select_folder": "فولڈر منتخب کریں",
        "supported_formats": "تعاون یافتہ فارمیٹس",
        "format_docx": ".docx (Word) — مکمل تعاون یافتہ",
        "format_md": ".md (Obsidian) — جلد آرہا ہے",
        "format_notion": "Notion ایکسپورٹ — جلد آرہا ہے",
        "format_pdf": "PDF — جلد آرہا ہے",

        "ai_title": "AI ترتیب دیں",
        "ai_subtitle": "Demiurgos کو اپنے LLM فراہم کنندگان سے جوڑیں۔ ٹیکسٹ ماڈل ضروری ہے؛ ویژن اختیاری ہے۔",
        "provider_label": "فراہم کنندہ",
        "endpoint_label": "اینڈپوائنٹ URL",
        "api_key_label": "API کلید",
        "model_text_label": "ٹیکسٹ ماڈل",
        "model_vision_label": "ویژن ماڈل",
        "test_connection": "کنکشن ٹیسٹ کریں",
        "testing": "کنکشن ٹیسٹ ہو رہا ہے…",
        "connection_success": "کنکشن کامیاب — {count} ماڈل ملے",
        "connection_error": "کنکشن ناکام",
        "same_as_text": "ٹیکسٹ ماڈل جیسا ہی",
        "vision_warning": "{model} ویژن کو سپورٹ نہیں کرتا۔ ویژن کاموں کے لیے 👁️ نشان والا ماڈل منتخب کریں۔",
        "save_config": "ترتیب محفوظ کریں",
        "select_model": "ماڈل منتخب کریں…",
        "select_provider": "فراہم کنندہ منتخب کریں…",
        "discover_models": "ماڈل دریافت کریں",

        "images_title": "تصویر سازی",
        "images_subtitle": "اختیاری — بصری کہانی کے لیے تصویر سازی کا فراہم کنندہ ترتیب دیں۔",
        "skip_for_now": "ابھی چھوڑیں",
        "configure_later": "بعد میں ترتیب دیں",

        "chats_title": "چیٹ پلیٹ فارم",
        "chats_subtitle": "اختیاری — موبائل رسائی کے لیے Demiurgos کو Telegram یا Discord سے جوڑیں۔",

        "backup_title": "بیک اپ اور سنک",
        "backup_subtitle": "اختیاری — اپنی دنیاؤں اور لور کا خودکار بیک اپ سیٹ کریں۔",

        "summary_title": "شروع کرنے کے لیے تیار",
        "summary_subtitle": "یہاں آپ کی ترتیب کا خلاصہ ہے۔ آپ بعد میں کچھ بھی تبدیل کر سکتے ہیں۔",
        "start_using": "Demiurgos استعمال کرنا شروع کریں",
        "go_back": "واپس جائیں",
        "world_created": "دنیا بن گئی",
        "ai_configured": "AI ترتیب دی گئی",
        "configured": "ترتیب شدہ",
        "skipped": "چھوڑ دیا گیا",
        "edit": "ترمیم کریں",

        "next": "اگلا",
        "back": "پچھلا",
        "step_x_of_y": "مرحلہ {current} / {total}",

        "error_generic": "کچھ غلط ہو گیا۔ براہ کرم دوبارہ کوشش کریں۔",
        "error_required_field": "یہ فیلڈ ضروری ہے۔",
        "error_connection": "سرور سے رابطہ نہیں ہو سکا۔ اپنا نیٹ ورک چیک کریں اور دوبارہ کوشش کریں۔",

        "vision_tag_confirmed": "👁️ ویژن",
        "vision_tag_text_only": "✍️ ٹیکسٹ",
        "vision_tag_unknown": "❓ نامعلوم",
    },
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def t(lang: str, key: str) -> str:
    """Return the translation for *key* in *lang*, with safe fallback.

    Fallback chain (first match wins):
    1.  Exact match in requested language
    2.  English fallback for the same key
    3.  The *key* string itself (never returns empty string)

    Examples::

        >>> t("es-ar", "welcome_title")
        'Bienvenido a Demiurgos'

        >>> t("es", "welcome_title")
        'Bienvenido a Demiurgos'

        >>> t("zz", "welcome_title")       # unknown lang → English
        'Welcome to Demiurgos'

        >>> t("en", "nonexistent_key")
        'nonexistent_key'
    """
    lang_dict = _LANGUAGES.get(lang)

    # Exact match in requested language
    if lang_dict is not None:
        value = lang_dict.get(key)
        if value is not None:
            return value

    # Fallback to English
    en_dict = _LANGUAGES.get(_FALLBACK_LANG, {})
    value = en_dict.get(key)
    if value is not None:
        return value

    # Last resort: return the key itself (never crash, never empty)
    return key


def get_text(key: str, lang: str) -> str:
    """Alias for :func:`t` with *key* first, for callers that prefer that order.

    Equivalent to ``t(lang, key)``.
    """
    return t(lang, key)


def get_language_name(lang_code: str) -> str:
    """Return the human-readable name for *lang_code* in that language.

    If the code is unknown, returns the code itself.

    Examples::

        >>> get_language_name("es-ar")
        'Español (rioplatense)'

        >>> get_language_name("en")
        'English'
    """
    return _LANGUAGE_NAMES.get(lang_code, lang_code)


def available_languages() -> list[str]:
    """Return the list of supported language codes, in definition order."""
    return list(_LANGUAGES.keys())


# ---------------------------------------------------------------------------
# Jinja2 integration
# ---------------------------------------------------------------------------


def register_with_jinja(
    templates: object,
    lang_getter: Callable[[], str],
) -> None:
    """Register ``t(key)`` and ``lang_name()`` as template globals.

    *templates* must be a ``jinja2.Environment`` or any object that exposes a
    ``.globals`` dict (such as FastAPI's ``Jinja2Templates().env``).

    *lang_getter* is a zero-argument callable that returns the current
    language code for the request (e.g. ``lambda: session["language"]``).

    After registration, templates can use::

        {{ t("welcome_title") }}
        {{ lang_name() }}
        {{ t("step_x_of_y", current=2, total=7) }}

    Usage in ``main.py``::

        from i18n import register_with_jinja
        register_with_jinja(templates.env, lambda: request.state.language)
    """
    env = getattr(templates, "env", templates)

    def _t(key: str, **fmt_kwargs: object) -> str:
        text = t(lang_getter(), key)
        if fmt_kwargs:
            return text.format(**fmt_kwargs)
        return text

    env.globals["t"] = _t
    env.globals["lang_name"] = lambda: get_language_name(lang_getter())
